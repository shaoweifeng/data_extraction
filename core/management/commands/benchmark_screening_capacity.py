"""Repeatable Stage 12 database capacity benchmark for screening storage."""

import hashlib
import json
import os
import platform
import resource
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import DataFile, Project
from core.screening.models import (
    ReferenceImportBatch,
    ReferenceImportFile,
    ScreeningCorpus,
    ScreeningReference,
    ScreeningReferenceRawMetadata,
    ScreeningResult,
    ScreeningRun,
)
from core.screening.services.dedup_service import (
    build_dedup_run,
    complete_dedup_run,
    create_dedup_run,
)
from core.services.project_service import initialize_project


def _now():
    return time.perf_counter()


def _elapsed(start):
    return round(time.perf_counter() - start, 4)


def _rss_mib():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports KiB.
    return round(value / (1024 * 1024) if platform.system() == 'Darwin' else value / 1024, 2)


class Command(BaseCommand):
    help = '运行阶段 12 的数据库容量基准并输出 JSON 报告（默认完成后清理数据）'

    def add_arguments(self, parser):
        parser.add_argument('--references', type=int, default=100000)
        parser.add_argument('--batch-size', type=int, default=1000)
        parser.add_argument('--duplicate-every', type=int, default=100)
        parser.add_argument('--output', type=Path)
        parser.add_argument('--skip-dedup', action='store_true')
        parser.add_argument('--skip-parser', action='store_true')
        parser.add_argument('--skip-export', action='store_true')
        parser.add_argument('--skip-results', action='store_true')
        parser.add_argument('--keep-data', action='store_true')
        parser.add_argument('--execute', action='store_true')

    def handle(self, *args, **options):
        count = options['references']
        batch_size = options['batch_size']
        duplicate_every = options['duplicate_every']
        if not options['execute']:
            raise CommandError('这是写入型容量测试；确认测试数据库后请显式添加 --execute。')
        if count < 0 or count > 100001:
            raise CommandError('--references 必须位于 0..100001。')
        if batch_size < 1 or batch_size > 5000:
            raise CommandError('--batch-size 必须位于 1..5000。')
        if duplicate_every < 2:
            raise CommandError('--duplicate-every 必须至少为 2。')

        token = uuid.uuid4().hex[:10]
        user = None
        project = None
        report = {
            'schema_version': 1,
            'started_at': timezone.now().isoformat(),
            'requested_references': count,
            'batch_size': batch_size,
            'duplicate_every': duplicate_every,
            'environment': self._environment(),
            'measurements': {},
        }
        try:
            if not options['skip_parser']:
                report['measurements']['ris_parse'] = self._benchmark_ris_parser(count)

            user = get_user_model().objects.create_user(
                username=f'capacity-{token}', password=uuid.uuid4().hex,
            )
            project = Project.objects.create(name=f'Capacity benchmark {token}', owner=user)
            initialize_project(project, user)
            corpus, batch, import_file = self._create_import_shell(project, user, count)

            start = _now()
            self._seed_references(
                project, corpus, batch, import_file, count, batch_size, duplicate_every,
            )
            report['measurements']['reference_seed'] = {
                'seconds': _elapsed(start),
                'rows_per_second': round(count / max(time.perf_counter() - start, 0.0001), 2),
                'peak_rss_mib': _rss_mib(),
            }
            corpus.active_reference_count = count
            corpus.save(update_fields=['active_reference_count', 'updated_at'])

            client = Client()
            client.force_login(user)
            report['measurements']['ai_input_first_page'] = self._measure_request(
                client,
                f'/api/projects/{project.id}/ai_screen_inputs/?limit=50&offset=0',
            )
            last_offset = max(0, count - 50)
            report['measurements']['ai_input_last_page'] = self._measure_request(
                client,
                f'/api/projects/{project.id}/ai_screen_inputs/?limit=50&offset={last_offset}',
            )

            dedup_run = None
            if count and not options['skip_dedup']:
                start = _now()
                dedup_run = build_dedup_run(create_dedup_run(project=project, created_by=user).id)
                dedup_run = complete_dedup_run(dedup_run.id)
                report['measurements']['dedup'] = {
                    'seconds': _elapsed(start),
                    'total': dedup_run.total_count,
                    'kept': dedup_run.kept_count,
                    'duplicates': dedup_run.duplicate_count,
                    'groups': dedup_run.group_count,
                    'peak_rss_mib': _rss_mib(),
                }
                if dedup_run.group_count:
                    report['measurements']['dedup_group_first_page'] = self._measure_request(
                        client,
                        f'/api/projects/{project.id}/dedup-runs/{dedup_run.id}/groups/?page=1&page_size=20',
                    )
                    last_group_page = (dedup_run.group_count + 19) // 20
                    report['measurements']['dedup_group_last_page'] = self._measure_request(
                        client,
                        f'/api/projects/{project.id}/dedup-runs/{dedup_run.id}/groups/?page={last_group_page}&page_size=20',
                    )

            if count and not options['skip_results']:
                start = _now()
                run = self._seed_results(project, corpus, dedup_run, batch_size)
                report['measurements']['screening_result_seed'] = {
                    'seconds': _elapsed(start),
                    'rows': run.total_count,
                    'peak_rss_mib': _rss_mib(),
                }
                review_step = project.stages.get(stage_key='SCREEN_1').steps.get(step_key='review')
                report['measurements']['review_first_page'] = self._measure_request(
                    client,
                    f'/api/review/list/?project={project.id}&step={review_step.id}&run={run.id}&page=1&page_size=50',
                )
                last_page = max(1, (run.total_count + 49) // 50)
                report['measurements']['review_last_page'] = self._measure_request(
                    client,
                    f'/api/review/list/?project={project.id}&step={review_step.id}&run={run.id}&page={last_page}&page_size=50',
                )
                report['measurements']['review_stats'] = self._measure_request(
                    client,
                    f'/api/review/stats/?project={project.id}&run={run.id}',
                )
                if not options['skip_export']:
                    report['measurements']['streaming_export'] = self._benchmark_export(run)

            report['database'] = self._database_footprint(project)
            report['finished_at'] = timezone.now().isoformat()
            report['peak_rss_mib'] = _rss_mib()
            report['project_id'] = project.id if options['keep_data'] else None
        finally:
            if project is not None and not options['keep_data']:
                project.delete()
            if user is not None and not options['keep_data']:
                user.delete()

        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if options['output']:
            options['output'].parent.mkdir(parents=True, exist_ok=True)
            options['output'].write_text(rendered + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'容量报告已写入 {options["output"]}'))
        self.stdout.write(rendered)

    def _benchmark_ris_parser(self, count):
        """Generate and parse a real RIS stream without retaining parsed records."""
        from core.screening.parsers import iter_file

        with tempfile.TemporaryDirectory(prefix='screening-capacity-parse-') as temp_dir:
            source = Path(temp_dir) / 'capacity.ris'
            write_start = _now()
            with source.open('w', encoding='utf-8') as output:
                for position in range(1, count + 1):
                    output.write(
                        'TY  - JOUR\n'
                        f'TI  - Capacity parser title {position}\n'
                        'AU  - Capacity, Author\n'
                        'PY  - 2026\n'
                        f'AB  - Capacity parser abstract {position}\n'
                        f'DO  - 10.9999/capacity.{position}\n'
                        'ER  -\n'
                    )
            input_bytes = source.stat().st_size
            write_seconds = _elapsed(write_start)

            parse_start = _now()
            parsed = sum(1 for _record in iter_file(str(source)))
            parse_seconds = _elapsed(parse_start)
        if parsed != count:
            raise CommandError(f'RIS 容量解析数量不一致：期望 {count}，实际 {parsed}')
        return {
            'rows': parsed,
            'input_bytes': input_bytes,
            'fixture_write_seconds': write_seconds,
            'parse_seconds': parse_seconds,
            'rows_per_second': round(parsed / max(parse_seconds, 0.0001), 2),
            'process_peak_rss_mib': _rss_mib(),
        }

    def _benchmark_export(self, run):
        """Use production exporters to write XLSX, RIS and XML in one bounded pass."""
        from core.screening.exporters.excel import ScreeningExcelExporter
        from core.screening.exporters.ris import ScreeningRisExporter
        from core.screening.exporters.xml import ScreeningXmlExporter
        from core.screening.services.final_results import iter_resolved_screening_records

        class BenchmarkLogger:
            def info(self, *_args, **_kwargs):
                return None

            warning = info
            error = info

        with tempfile.TemporaryDirectory(prefix='screening-capacity-export-') as temp_dir:
            workspace = Path(temp_dir)
            handler = SimpleNamespace(
                workspace=workspace,
                logger=BenchmarkLogger(),
                _load_extraction_field_names=lambda: [],
            )
            excel_exporter = ScreeningExcelExporter(handler)
            ris_exporter = ScreeningRisExporter(handler)
            xml_path = workspace / 'screening_results_all_capacity.xml'
            ris_path = workspace / 'screening_results_included_capacity.ris'
            counts = {'all': 0, 'included': 0, 'excluded': 0}

            def prepared_results():
                for resolved in iter_resolved_screening_records(run, batch_size=500):
                    result = resolved.as_payload()
                    reference = resolved.reference
                    result['_export_manual_review'] = resolved.manual_review
                    result['_export_final_decision'] = resolved.final_decision
                    result['_export_include_excel'] = True
                    result['_export_xml_fields'] = {
                        'ReferenceType': reference.publication_type,
                        'Title': reference.title,
                        'Author': '; '.join(reference.authors or []),
                        'Year': reference.publication_year,
                        'Journal': reference.journal,
                        'Volume': reference.volume,
                        'Issue': reference.issue,
                        'Page': reference.pages,
                        'Date': reference.publication_date,
                        'Doi': reference.doi,
                        'PMCID': reference.pmcid,
                        'Abstract': reference.abstract,
                        'URL': reference.url,
                        'Address': reference.address,
                    }
                    yield result

            start = _now()
            with CaptureQueriesContext(connection) as queries:
                with (
                    xml_path.open('w', encoding='utf-8') as xml_output,
                    ris_path.open('w', encoding='utf-8') as ris_output,
                ):
                    ScreeningXmlExporter.write_header(xml_output)

                    def write_side_formats(result, fields, final_decision):
                        counts['all'] += 1
                        counts[final_decision] += 1
                        ScreeningXmlExporter.write_record(
                            xml_output, result, fields, final_decision,
                        )
                        if final_decision == 'included':
                            ris_exporter._write_record(ris_output, result, fields)

                    excel_path = excel_exporter._generate_excel(
                        prepared_results(), 'all', 'capacity', 'benchmark', {}, [],
                        on_record=write_side_formats,
                    )
                    ScreeningXmlExporter.write_footer(xml_output)
            seconds = _elapsed(start)
            if excel_path is None or counts['all'] != run.total_count:
                raise CommandError(
                    f'容量导出数量不一致：期望 {run.total_count}，实际 {counts["all"]}'
                )
            output_bytes = {
                'xlsx': excel_path.stat().st_size,
                'xml': xml_path.stat().st_size,
                'ris': ris_path.stat().st_size,
            }
        return {
            'rows': counts,
            'seconds': seconds,
            'rows_per_second': round(counts['all'] / max(seconds, 0.0001), 2),
            'sql_queries': len(queries),
            'output_bytes': output_bytes,
            'process_peak_rss_mib': _rss_mib(),
        }

    def _environment(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT VERSION()')
            db_version = cursor.fetchone()[0]
        return {
            'os': platform.platform(),
            'python': platform.python_version(),
            'database_engine': connection.vendor,
            'database_version': db_version,
            'cpu_count': os.cpu_count(),
        }

    def _create_import_shell(self, project, user, count):
        corpus = ScreeningCorpus.objects.create(
            project=project, revision=1, active_source_file_count=1,
        )
        batch = ReferenceImportBatch.objects.create(
            project=project,
            corpus=corpus,
            created_by=user,
            operation=ReferenceImportBatch.Operation.ADD,
            status=ReferenceImportBatch.Status.COMPLETED,
            base_revision=0,
            target_revision=1,
            published_revision=1,
            file_count=1,
            accepted_count=count,
        )
        source = DataFile.objects.create(
            project=project,
            filename='capacity-synthetic.ris',
            file_size=0,
            file_type='ris',
            created_by=user,
        )
        import_file = ReferenceImportFile.objects.create(
            import_batch=batch,
            source_file=source,
            raw_file='',
            original_filename='capacity-synthetic.ris',
            sha256='f' * 64,
            source_format='ris',
            parse_status=ReferenceImportFile.ParseStatus.PARSED,
            introduced_revision=1,
            detected_count=count,
            parsed_count=count,
        )
        corpus.last_import_batch = batch
        corpus.save(update_fields=['last_import_batch', 'updated_at'])
        return corpus, batch, import_file

    def _seed_references(self, project, corpus, batch, import_file, count, batch_size, duplicate_every):
        for start in range(1, count + 1, batch_size):
            stop = min(count + 1, start + batch_size)
            rows = []
            for position in range(start, stop):
                group = position // duplicate_every
                is_duplicate_pair = position % duplicate_every in (0, 1)
                title = f'Duplicate capacity title {group}' if is_duplicate_pair else f'Unique capacity title {position}'
                normalized = ''.join(char.lower() for char in title if char.isalnum())
                rows.append(ScreeningReference(
                    project=project,
                    corpus=corpus,
                    import_batch=batch,
                    import_file=import_file,
                    source_file=import_file.source_file,
                    source_record_index=position,
                    source_identifier=str(position),
                    introduced_revision=1,
                    title=title,
                    abstract=f'Synthetic abstract {position}',
                    authors=['Capacity Author'],
                    publication_year='2026',
                    normalized_title_hash=hashlib.sha256(normalized.encode()).hexdigest(),
                    record_hash=hashlib.sha256(f'record:{position}'.encode()).hexdigest(),
                ))
            ScreeningReference.objects.bulk_create(rows, batch_size=batch_size)
            stored = ScreeningReference.objects.filter(
                import_file=import_file,
                source_record_index__gte=start,
                source_record_index__lt=stop,
            ).only('id')
            ScreeningReferenceRawMetadata.objects.bulk_create([
                ScreeningReferenceRawMetadata(
                    reference_id=row.id,
                    import_file=import_file,
                    source_format='ris',
                    raw_fields={'synthetic': True},
                    raw_size_bytes=18,
                    raw_hash=hashlib.sha256(f'raw:{row.id}'.encode()).hexdigest(),
                    parser_version='capacity-v1',
                )
                for row in stored
            ], batch_size=batch_size)

    def _seed_results(self, project, corpus, dedup_run, batch_size):
        references = ScreeningReference.objects.filter(corpus=corpus).active_at(corpus.revision)
        if dedup_run is not None:
            duplicate_ids = dedup_run.members.filter(role='duplicate').values('reference_id')
            references = references.exclude(id__in=duplicate_ids)
        total = references.count()
        run = ScreeningRun.objects.create(
            project=project,
            corpus=corpus,
            corpus_revision=corpus.revision,
            dedup_run=dedup_run,
            status=ScreeningRun.Status.COMPLETED,
            total_count=total,
            processed_count=total,
            included_count=(total + 1) // 2,
            excluded_count=total // 2,
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        pending = []
        for reference_id in references.order_by('id').values_list('id', flat=True).iterator(chunk_size=batch_size):
            decision = 'included' if reference_id % 2 else 'excluded'
            pending.append(ScreeningResult(
                screening_run=run,
                reference_id=reference_id,
                status=ScreeningResult.Status.COMPLETED,
                decision=decision,
                consensus=decision,
                reason='' if decision == 'included' else 'Synthetic exclusion',
            ))
            if len(pending) >= batch_size:
                ScreeningResult.objects.bulk_create(pending, batch_size=batch_size)
                pending = []
        if pending:
            ScreeningResult.objects.bulk_create(pending, batch_size=batch_size)
        return run

    def _measure_request(self, client, path):
        with CaptureQueriesContext(connection) as queries:
            start = _now()
            response = client.get(path, HTTP_HOST='localhost')
            seconds = _elapsed(start)
        if response.status_code != 200:
            raise CommandError(f'基准请求失败 {response.status_code}: {path} {response.content[:300]!r}')
        return {
            'seconds': seconds,
            'sql_queries': len(queries),
            'response_bytes': len(response.content),
            'status_code': response.status_code,
        }

    def _database_footprint(self, project):
        tables = [
            'plat_screening_reference',
            'plat_screening_reference_raw',
            'plat_reference_duplicate_group',
            'plat_reference_duplicate_member',
            'plat_screening_result',
        ]
        try:
            with connection.cursor() as cursor:
                # InnoDB information_schema estimates can remain stale after bulk writes.
                # Refresh optimizer statistics before recording the table-level footprint.
                # ANALYZE TABLE implicitly commits on MySQL, so never run it inside
                # Django's TestCase/transaction.atomic isolation boundary.
                analyzed = not connection.in_atomic_block
                if analyzed:
                    for table in tables:
                        cursor.execute(f'ANALYZE TABLE `{table}`')
                placeholders = ','.join(['%s'] * len(tables))
                cursor.execute(
                    f'SELECT table_name, data_length, index_length FROM information_schema.tables '
                    f'WHERE table_schema = DATABASE() AND table_name IN ({placeholders})',
                    tables,
                )
                result = {
                    name: {'data_bytes': int(data or 0), 'index_bytes': int(index or 0)}
                    for name, data, index in cursor.fetchall()
                }
                result['_scope'] = (
                    'whole_table_after_analyze'
                    if analyzed else 'whole_table_estimate_without_analyze'
                )
                return result
        except Exception as exc:
            return {'unavailable': str(exc)}
