"""Streaming bibliography/PDF renderers; task lifecycle and snapshots live in exports.py."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from django.conf import settings
from core.bibliography import BIBLIOGRAPHY_FIELDS
from core.rescreening.errors import RescreenError


def _text(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value if value is not None else '')


def _xml_text(value):
    # XML 1.0 excludes control chars; JSONL remains the lossless original representation.
    return ''.join(c for c in _text(value) if c in '\t\n\r' or '\u0020' <= c <= '\ud7ff' or '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff')


def write_export(job, path, tick):
    import xml.etree.ElementTree as ET
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from core.screening.exporters.ris import ScreeningRisExporter
    items = job.items.select_related('asset').order_by('pk').iterator(chunk_size=100)
    if job.format == 'xlsx':
        from openpyxl.worksheet._writer import WorksheetWriter, ALL_TEMP_FILES
        workbook = Workbook(write_only=True)
        job._export_workbook = workbook
        def sheet(name):
            result = workbook.create_sheet(name)
            # Keep openpyxl XML in this job's private spool too, so hard-kill orphans can expire.
            result._writer = WorksheetWriter(result, out=str(path.parent / f'sheet_{len(workbook.worksheets)}.xml'))
            result._writer.write_top()
            ALL_TEMP_FILES.append(result._writer.out)
            return result
        main = sheet('复筛结果')
        overflow = sheet('长字段与原始元数据')
        overflow_count, overflow_number = 1, 1
        headers = ['reference_id', *BIBLIOGRAPHY_FIELDS, 'decision', 'exclusion_reason', 'note', 'needs_reconfirmation', 'ai_suggestion']
        main.append(headers)
        overflow.append(['reference_id', 'field', 'part', 'text（按 part 拼接还原）'])

        def cell(sheet, value):
            result = WriteOnlyCell(sheet, value=ILLEGAL_CHARACTERS_RE.sub('', _text(value)))
            result.data_type = 's'  # Prevent formulas/URLs from becoming executable cells.
            return result

        def append_overflow(reference_id, key, part, value):
            nonlocal overflow, overflow_count, overflow_number
            if overflow_count >= 1000000:
                overflow_number += 1
                overflow = sheet(f'长字段与原始元数据_{overflow_number}')
                overflow.append(['reference_id', 'field', 'part', 'text（按 part 拼接还原）'])
                overflow_count = 1
            overflow.append([reference_id, key, part, cell(overflow, value)])
            overflow_count += 1

        for index, item in enumerate(items, 1):
            p = item.payload
            values = {**p['bibliography'], **p, 'exclusion_reason': (p['review'] or {}).get('exclusion_reason', ''), 'note': (p['review'] or {}).get('note', '')}
            cells = []
            for key in headers:
                value = _text(values.get(key, ''))
                if len(value) > 15000:
                    for part, offset in enumerate(range(0, len(value), 15000), 1):
                        append_overflow(item.reference_id_snapshot, key, part, value[offset:offset+15000])
                    value = '完整内容见长字段与原始元数据工作表'
                cells.append(cell(main, value))
            main.append(cells)
            # Preserve unmapped vendor fields and AI extraction fields without inventing columns.
            value = json.dumps(p, ensure_ascii=False)
            for part, offset in enumerate(range(0, len(value), 15000), 1):
                append_overflow(item.reference_id_snapshot, 'complete_record_json', part, value[offset:offset+15000])
            tick(index)
        workbook.save(path)
    elif job.format == 'pdf':
        with ZipFile(path, 'w', compression=ZIP_DEFLATED, allowZip64=True) as archive:
            manifest_path = path.with_suffix('.manifest.json')
            total = 0
            with manifest_path.open('w', encoding='utf-8') as manifest:
                manifest.write(json.dumps({'mode': job.mode, 'scope': job.scope, 'fingerprint': job.fingerprint})[:-1] + ', "files": [\n')
                for index, item in enumerate(items, 1):
                    entry = {'reference_id': item.reference_id_snapshot, 'title': item.payload['bibliography']['title'], 'file': None}
                    if item.asset:
                        name = f'pdf/reference_{item.reference_id_snapshot}.pdf'
                        entry['file'] = name
                        entry['sha256'] = item.asset.sha256
                        checksum = hashlib.sha256()
                        with item.asset.raw_file.storage.open(item.asset.raw_file.name, 'rb') as source, archive.open(name, 'w', force_zip64=True) as target:
                            while body := source.read(1024*1024):
                                total += len(body)
                                if total > settings.RESCREEN_EXPORT_MAX_BYTES:
                                    raise RescreenError('export_too_large', 'PDF 包超过大小上限。', status=413)
                                checksum.update(body)
                                target.write(body)
                                tick(index-1)
                        if checksum.hexdigest() != item.asset.sha256:
                            raise RescreenError('asset_checksum_mismatch', '全文文件校验失败，导出已中止。')
                    manifest.write((',' if index > 1 else '') + json.dumps(entry, ensure_ascii=False) + '\n')
                    tick(index)
                manifest.write(']}\n')
            archive.write(manifest_path, 'manifest.json')
    else:
        with open(path, 'w', encoding='utf-8') as output:
            if job.format == 'xml':
                output.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<References mode="{job.mode}" scope="{job.scope}">\n')
            for index, item in enumerate(items, 1):
                p = item.payload
                if job.format == 'metadata':
                    output.write(json.dumps(p, ensure_ascii=False) + '\n')
                elif job.format == 'xml':
                    node = ET.Element('Reference', {'id': str(item.reference_id_snapshot), 'decision': p['decision']})
                    from core.screening.exporters.xml import ScreeningXmlExporter
                    # Same public bibliography tags as initial screening; retain full JSON alongside.
                    mapping = dict(zip((field for field,tag in ScreeningXmlExporter.FIELD_TAGS),
                        ('publication_type', 'title', 'authors', 'publication_year', 'journal', 'volume', 'issue', 'pages',
                         'publication_date', 'doi', 'pmid', 'pmcid', 'isbn', 'issn', 'abstract', 'url', 'address',
                         'keywords', 'language', 'publisher', 'database', 'organization', 'source_identifier')))
                    for field, tag in ScreeningXmlExporter.FIELD_TAGS:
                        value = p['bibliography'][mapping[field]]
                        if field == 'Author':
                            authors = ET.SubElement(node, tag)
                            for author in value:
                                ET.SubElement(authors, 'Author').text = _xml_text(author)
                            continue
                        if field == 'Keywords':
                            value = '; '.join(value)
                        ET.SubElement(node, tag).text = _xml_text(value)
                    for key, value in p.items():
                        ET.SubElement(node, key).text = _xml_text(value)
                    output.write(ET.tostring(node, encoding='unicode') + '\n')
                else:
                    from io import StringIO
                    b = p['bibliography']
                    fields = {field: b[key] for field, key in [('Title','title'), ('Author','authors'), ('Year','publication_year'),
                        ('Journal','journal'), ('Volume','volume'), ('Issue','issue'), ('Page','pages'), ('Date','publication_date'),
                        ('Doi','doi'), ('PMID','pmid'), ('PMCID','pmcid'), ('ISBN','isbn'), ('ISSN','issn'), ('Abstract','abstract'),
                        ('URL','url'), ('Address','address'), ('Keywords','keywords'), ('Language','language'), ('Publisher','publisher'),
                        ('Database','database'), ('Organization','organization'), ('SourceIdentifier','source_identifier'), ('ReferenceType','publication_type')]}
                    # Newlines must not inject additional RIS records/tags. Spaces preserve reading order.
                    fields = {k: [str(x).replace('\n',' ').replace('\r',' ') for x in v] if isinstance(v,list)
                              else str(v).replace('\n',' ').replace('\r',' ') for k,v in fields.items()}
                    record = StringIO()
                    ScreeningRisExporter(None)._write_record(record, {}, fields)
                    output.write(record.getvalue().removesuffix('ER  -\n'))
                    output.write('N1  - MetaFlow ' + json.dumps(p, ensure_ascii=False) + '\nER  -\n')
                tick(index)
            if job.format == 'xml':
                output.write('</References>\n')

