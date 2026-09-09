"""RIS exporter for included screening results."""

from pathlib import Path
from typing import Dict, Iterable, Optional

from core.screening.exporters.common import format_conflict_detail


class ScreeningRisExporter:
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def _write_record(self, output, result: Dict, xml: Optional[Dict] = None) -> None:
        """向已打开的 RIS 文件追加一篇文献。"""
        xml = xml if xml is not None else (
            self._load_xml_fields(result.get('source_xml', ''))
            if result.get('source_xml') else {}
        )

        def _get(xml_key, json_key, default=''):
            return xml.get(xml_key) or result.get(json_key, '') or default

        ref_type_raw = xml.get('ReferenceType', '')
        ris_type_map = {
            'Journal Article': 'JOUR', 'Review': 'JOUR', 'Clinical Trial': 'JOUR',
            'Book': 'BOOK', 'Book Chapter': 'CHAP', 'Conference Paper': 'CONF',
            'Thesis': 'THES', 'Report': 'RPRT', 'Web Page': 'ELEC',
        }
        output.write(f"TY  - {ris_type_map.get(ref_type_raw, 'JOUR')}\n")

        title = _get('Title', 'title')
        if title:
            output.write(f"TI  - {title}\n")

        authors_raw = xml.get('Author') or result.get('authors', '')
        if authors_raw:
            authors = authors_raw if isinstance(authors_raw, list) else str(authors_raw).split('; ')
            for author in authors:
                if author and str(author).strip():
                    output.write(f"AU  - {str(author).strip()}\n")

        for tag, xml_key, json_key in [
            ('PY', 'Year', 'year'),
            ('JO', 'Journal', 'journal'),
            ('VL', 'Volume', 'volume'),
            ('IS', 'Issue', 'issue'),
            ('DO', 'Doi', 'doi'),
            ('AB', 'Abstract', 'abstract'),
            ('AD', 'Address', 'address'),
        ]:
            value = _get(xml_key, json_key)
            if value:
                value = str(value)[:4] if tag == 'PY' else value
                output.write(f"{tag}  - {value}\n")

        page = _get('Page', 'page')
        if page and '-' in str(page):
            start_page, end_page = str(page).split('-', 1)
            output.write(f"SP  - {start_page.strip()}\n")
            output.write(f"EP  - {end_page.strip()}\n")
        elif page:
            output.write(f"SP  - {page}\n")

        pmcid = _get('PMCID', 'pmcid')
        if pmcid:
            output.write(f"AN  - {pmcid}\n")
        url = _get('URL', 'url')
        if url:
            output.write(f"UR  - {url}\n")
        if result.get('_export_final_decision') == 'conflict':
            # N1 是 RIS 的 Notes 字段，确保下游导入后仍能识别这是豁免分歧，
            # 而不是已经得到明确“纳入”结论的文献。
            detail = format_conflict_detail(result).replace('\n', ' | ')
            output.write(f"N1  - {detail}\n")
        output.write('ER  -\n')

    def _generate_ris(self, results: Iterable[Dict], model_suffix: str, ts: str) -> Optional[Path]:
        """生成 RIS 文件，返回路径；失败返回 None。"""
        ris_path = self.workspace / f"screening_results_included_{model_suffix}_{ts}.ris"
        try:
            count = 0
            with open(ris_path, 'w', encoding='utf-8') as f:
                for result in results:
                    xml = result.get('_export_xml_fields')
                    self._write_record(f, result, xml)
                    count += 1

            self.logger.info(f"[导出] 生成 RIS: {count} 条")
            return ris_path
        except Exception as e:
            self.logger.error(f"[错误] 生成 RIS 失败: {e}")
            return None
