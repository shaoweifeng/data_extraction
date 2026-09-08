"""RIS exporter for included screening results."""

from pathlib import Path
from typing import Dict, List, Optional


class ScreeningRisExporter:
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def _generate_ris(self, results: List[Dict], model_suffix: str, ts: str) -> Optional[Path]:
        """生成 RIS 文件，返回路径；失败返回 None。"""
        ris_path = self.workspace / f"screening_results_included_{model_suffix}_{ts}.ris"
        try:
            with open(ris_path, 'w', encoding='utf-8') as f:
                for r in results:
                    source_xml = r.get('source_xml', '')
                    xml = self._load_xml_fields(source_xml) if source_xml else {}

                    def _get(xml_key, json_key, default=''):
                        return xml.get(xml_key) or r.get(json_key, '') or default

                    ref_type_raw = xml.get('ReferenceType', '')
                    ris_type_map = {
                        'Journal Article': 'JOUR', 'Review': 'JOUR', 'Clinical Trial': 'JOUR',
                        'Book': 'BOOK', 'Book Chapter': 'CHAP', 'Conference Paper': 'CONF',
                        'Thesis': 'THES', 'Report': 'RPRT', 'Web Page': 'ELEC',
                    }
                    f.write(f"TY  - {ris_type_map.get(ref_type_raw, 'JOUR')}\n")

                    title = _get('Title', 'title')
                    if title:
                        f.write(f"TI  - {title}\n")

                    authors_raw = xml.get('Author') or r.get('authors', '')
                    if authors_raw:
                        if isinstance(authors_raw, list):
                            for au in authors_raw:
                                if au and str(au).strip():
                                    f.write(f"AU  - {str(au).strip()}\n")
                        else:
                            for au in str(authors_raw).split('; '):
                                if au.strip():
                                    f.write(f"AU  - {au.strip()}\n")

                    for tag, xk, jk in [
                        ("PY", "Year", "year"),
                        ("JO", "Journal", "journal"),
                        ("VL", "Volume", "volume"),
                        ("IS", "Issue", "issue"),
                        ("DO", "Doi", "doi"),
                        ("AB", "Abstract", "abstract"),
                        ("AD", "Address", "address"),
                    ]:
                        val = _get(xk, jk)
                        if val:
                            if tag == "PY":
                                f.write(f"PY  - {str(val)[:4]}\n")
                            else:
                                f.write(f"{tag}  - {val}\n")

                    page = _get('Page', 'page')
                    if page and '-' in str(page):
                        parts = str(page).split('-', 1)
                        f.write(f"SP  - {parts[0].strip()}\n")
                        f.write(f"EP  - {parts[1].strip()}\n")
                    elif page:
                        f.write(f"SP  - {page}\n")

                    pmcid = _get('PMCID', 'pmcid')
                    if pmcid:
                        f.write(f"AN  - {pmcid}\n")

                    url = _get('URL', 'url')
                    if url:
                        f.write(f"UR  - {url}\n")

                    f.write("ER  -\n")

            self.logger.info(f"[导出] 生成 RIS: {len(results)} 条")
            return ris_path
        except Exception as e:
            self.logger.error(f"[错误] 生成 RIS 失败: {e}")
            return None
