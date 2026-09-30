"""Database deduplication and paginated detail API regression tests."""

import hashlib
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from core.artifacts.types import ArtifactType
from core.executors.executor import StepExecutor
from core.models import DataFile, Project, Task
from core.screening.parsers import parse_file
from core.screening.models import (
    DedupRun,
    ReferenceDuplicateMember,
    ReferenceImportBatch,
    ReferenceImportFile,
    ScreeningCorpus,
    ScreeningReference,
)
from core.screening.services.dedup_service import (
    DeduplicationCancelled,
    DeduplicationError,
    build_dedup_run,
    complete_dedup_run,
    create_dedup_run,
    iter_kept_references,
)
from core.screening.services.reference_persistence import normalize_title
from core.services.project_service import initialize_project


class ScreeningDedupTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('dedup-user', password='pw')
        self.project = Project.objects.create(name='Dedup project', owner=self.user)
        initialize_project(self.project, self.user)
        self.corpus = ScreeningCorpus.objects.create(
            project=self.project,
            revision=1,
            active_source_file_count=1,
        )
        self.batch = ReferenceImportBatch.objects.create(
            project=self.project,
            corpus=self.corpus,
            created_by=self.user,
            operation=ReferenceImportBatch.Operation.ADD,
            status=ReferenceImportBatch.Status.COMPLETED,
            base_revision=0,
            target_revision=1,
            published_revision=1,
        )
        self.data_file = DataFile.objects.create(
            project=self.project,
            filename='source.ris',
            file='screening/source.ris',
            file_size=100,
            file_type='ris',
            created_by=self.user,
        )
        self.import_file = ReferenceImportFile.objects.create(
            import_batch=self.batch,
            source_file=self.data_file,
            original_filename='source.ris',
            sha256='a' * 64,
            source_format='ris',
            introduced_revision=1,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def create_reference(self, position: int, title: str) -> ScreeningReference:
        normalized = normalize_title(title)
        reference = ScreeningReference.objects.create(
            project=self.project,
            corpus=self.corpus,
            import_batch=self.batch,
            import_file=self.import_file,
            source_file=self.data_file,
            source_record_index=position,
            introduced_revision=1,
            title=title,
            publication_year='2026',
            normalized_title_hash=hashlib.sha256(normalized.encode('utf-8')).hexdigest(),
            record_hash=f'{position:064x}',
        )
        ScreeningCorpus.objects.filter(pk=self.corpus.pk).update(
            active_reference_count=ScreeningReference.objects.filter(corpus=self.corpus).count(),
        )
        self.corpus.refresh_from_db()
        return reference

    def test_builds_revision_bound_groups_and_keeps_first_reference(self):
        first = self.create_reference(1, 'A Study!')
        duplicate = self.create_reference(2, 'a study')
        unique = self.create_reference(3, 'Another Study')
        untitled = self.create_reference(4, '---')

        run = create_dedup_run(project=self.project, created_by=self.user)
        run = build_dedup_run(run.id)

        self.assertEqual(run.status, DedupRun.Status.RUNNING)
        self.assertEqual((run.total_count, run.kept_count, run.duplicate_count, run.group_count), (4, 3, 1, 1))
        group = run.groups.get()
        self.assertEqual(group.representative_reference, first)
        self.assertEqual(group.member_count, 2)
        self.assertEqual(
            list(group.members.order_by('reference_id').values_list('role', flat=True)),
            [ReferenceDuplicateMember.Role.KEPT, ReferenceDuplicateMember.Role.DUPLICATE],
        )
        self.assertEqual(
            list(iter_kept_references(run)),
            [first, unique, untitled],
        )

        complete_dedup_run(run.id)
        run.refresh_from_db()
        self.corpus.refresh_from_db()
        self.assertEqual(run.status, DedupRun.Status.COMPLETED)
        self.assertEqual(self.corpus.last_dedup_run, run)
        self.assertNotIn(duplicate, list(iter_kept_references(run)))

    def test_cancelled_run_removes_partial_relations(self):
        self.create_reference(1, 'Same')
        self.create_reference(2, 'Same')
        run = create_dedup_run(project=self.project, created_by=self.user)

        with self.assertRaises(DeduplicationCancelled):
            build_dedup_run(run.id, should_cancel=lambda: True)

        run.refresh_from_db()
        self.assertEqual(run.status, DedupRun.Status.CANCELLED)
        self.assertFalse(run.groups.exists())

    def test_tampered_title_hash_fails_without_publishing_groups(self):
        reference = self.create_reference(1, 'Hash checked')
        ScreeningReference.objects.filter(pk=reference.pk).update(normalized_title_hash='0' * 64)
        run = create_dedup_run(project=self.project, created_by=self.user)

        with self.assertRaisesMessage(DeduplicationError, '哈希校验失败'):
            build_dedup_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, DedupRun.Status.FAILED)
        self.assertFalse(run.groups.exists())

    def test_revision_conflict_prevents_publication(self):
        self.create_reference(1, 'One')
        run = build_dedup_run(create_dedup_run(project=self.project).id)
        ScreeningCorpus.objects.filter(pk=self.corpus.pk).update(revision=2)

        with self.assertRaisesMessage(DeduplicationError, '文献集已发生变化'):
            complete_dedup_run(run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, DedupRun.Status.FAILED)
        self.assertFalse(run.groups.exists())

    def test_group_and_member_apis_reach_group_101_and_cap_page_sizes(self):
        for index in range(1, 102):
            self.create_reference(index * 2 - 1, f'Duplicate title {index}')
            self.create_reference(index * 2, f'duplicate title {index}')
        run = build_dedup_run(create_dedup_run(project=self.project).id)
        run = complete_dedup_run(run.id)

        groups_url = f'/api/projects/{self.project.id}/dedup-runs/{run.id}/groups/'
        first_page = self.client.get(groups_url, {'page': 1, 'page_size': 20}).json()
        fifth_page = self.client.get(groups_url, {'page': 5, 'page_size': 20}).json()
        response = self.client.get(groups_url, {'page': 6, 'page_size': 20})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['count'], 101)
        self.assertEqual(payload['total_pages'], 6)
        self.assertEqual(len(first_page['results']), 20)
        self.assertEqual(first_page['results'][0]['sequence'], 1)
        self.assertEqual(len(fifth_page['results']), 20)
        self.assertEqual(fifth_page['results'][-1]['sequence'], 100)
        self.assertEqual(len(payload['results']), 1)
        self.assertEqual(payload['results'][0]['sequence'], 101)
        self.assertEqual(
            self.client.get(groups_url, {'page': 7, 'page_size': 20}).json()['results'],
            [],
        )
        group_id = payload['results'][0]['id']

        response = self.client.get(
            f'/api/projects/{self.project.id}/dedup-runs/{run.id}/groups/{group_id}/members/',
            {'page_size': 999},
        )
        self.assertEqual(response.status_code, 200)
        member_payload = response.json()
        self.assertEqual(member_payload['page_size'], 200)
        self.assertEqual(member_payload['count'], 2)
        self.assertEqual([row['role'] for row in member_payload['results']], ['kept', 'duplicate'])

    def test_empty_groups_and_large_group_member_page_boundaries(self):
        self.create_reference(1, 'Unique title')
        empty_run = complete_dedup_run(
            build_dedup_run(create_dedup_run(project=self.project).id).id,
        )
        empty_url = f'/api/projects/{self.project.id}/dedup-runs/{empty_run.id}/groups/'
        empty_payload = self.client.get(empty_url).json()
        self.assertEqual(empty_payload['count'], 0)
        self.assertEqual(empty_payload['total_pages'], 0)
        self.assertEqual(empty_payload['results'], [])

        for position in range(2, 203):
            self.create_reference(position, 'One very large duplicate group')
        large_run = complete_dedup_run(
            build_dedup_run(create_dedup_run(project=self.project).id).id,
        )
        group = large_run.groups.get()
        self.assertEqual(group.member_count, 201)
        members_url = (
            f'/api/projects/{self.project.id}/dedup-runs/{large_run.id}/groups/'
            f'{group.id}/members/'
        )
        expected_lengths = {1: 50, 4: 50, 5: 1, 6: 0}
        for page, expected_length in expected_lengths.items():
            with self.subTest(page=page):
                payload = self.client.get(
                    members_url, {'page': page, 'page_size': 50},
                ).json()
                self.assertEqual(payload['count'], 201)
                self.assertEqual(payload['total_pages'], 5)
                self.assertEqual(len(payload['results']), expected_length)

        capped = self.client.get(members_url, {'page_size': 999}).json()
        self.assertEqual(capped['page_size'], 200)
        self.assertEqual(len(capped['results']), 200)

    def test_dedup_details_do_not_leak_across_projects(self):
        self.create_reference(1, 'Private')
        self.create_reference(2, 'private')
        run = complete_dedup_run(build_dedup_run(create_dedup_run(project=self.project).id).id)
        outsider = get_user_model().objects.create_user('dedup-outsider', password='pw')
        self.client.force_login(outsider)

        response = self.client.get(
            f'/api/projects/{self.project.id}/dedup-runs/{run.id}/groups/',
        )
        self.assertEqual(response.status_code, 404)

    def test_handler_publishes_compact_metadata_without_compatibility_xml(self):
        self.create_reference(1, 'Same title')
        self.create_reference(2, 'same title')
        unique = self.create_reference(3, 'Unique title')
        task = Task.objects.create(
            project=self.project,
            task_type='dedup',
            status='pending',
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with override_settings(BASE_DIR=root, MEDIA_ROOT=root / 'media'):
                executor = StepExecutor(task.id, 'dedup', self.project.id)
                executor.initialize()
                success = executor.execute()
                executor.finalize(success)

        self.assertTrue(success)
        step = self.project.stages.get(stage_key='SCREEN_1').steps.get(step_key='dedup')
        self.assertIn('dedup_run_id', step.metadata)
        self.assertNotIn('duplicate_details', step.metadata)
        outputs = DataFile.objects.filter(
            project=self.project,
            step=step,
            metadata__artifact_type='screening_dedup_reference_xml',
        )
        self.assertFalse(outputs.exists())
