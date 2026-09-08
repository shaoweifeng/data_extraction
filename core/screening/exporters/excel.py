"""Excel exporter for resolved screening results."""

from pathlib import Path
from typing import Dict, List, Optional

from core.screening.services.decision_service import ScreeningDecisionService
from core.screening.exporters.common import _lookup_criteria_id


class ScreeningExcelExporter:
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def _generate_excel(self, results: List[Dict], export_type: str,
                        model_suffix: str, ts: str,
                        manual_reviews: Dict,
                        criteria_list: List[str] = None) -> Optional[Path]:
        """生成 Excel 文件，返回文件路径；失败返回 None。

        Args:
            manual_reviews:  source_xml → ManualReview 对象的映射，显式传入避免闭包问题。
            criteria_list:   纳排标准文本列表（按序），用于人工理由反查编号。
        """
        if criteria_list is None:
            criteria_list = []
        try:
            import pandas as pd

            headers = [
                "id", "include_or_not", "manual_override", "exclusion_reason_id", "exclusion_reason",
                "ReferenceType", "Title", "Author", "Year", "Journal",
                "Volume", "Issue", "Page", "Date", "Doi", "PMCID", "Abstract", "URL", "Address",
                "source_xml",
            ]
            # 追加自定义提取字段
            extraction_field_names = self._load_extraction_field_names()
            headers.extend(extraction_field_names)

            rows = []
            for idx, result in enumerate(results, 1):
                source_xml = result.get("source_xml", "")
                mr = manual_reviews.get(source_xml)

                # ── 最终纳排决定（与 QA 导入共用同一领域规则）──────────────
                final_decision = ScreeningDecisionService.resolve(result, mr)
                include_or_not = 'yes' if final_decision == 'included' else 'no'
                manual_override_val = 'yes' if mr and mr.is_override else 'no'

                # ── 排除理由（人工 > AI）──────────────────────────────────
                if mr and mr.decision == 'excluded' and mr.reason:
                    # 人工审阅有明确排除理由，直接使用
                    exclusion_reason = mr.reason
                    # 通过文本反查 criteria 编号（1-based），找不到则留空
                    exclusion_reason_id = _lookup_criteria_id(mr.reason, criteria_list)
                else:
                    # 使用 AI 返回的合并理由（多模型时 ai_screen_handler 已合并）
                    exclusion_reason = result.get("exclusion_reason", "")
                    if not exclusion_reason and include_or_not == "no":
                        exclusion_reason = result.get("reasoning", "")
                    exclusion_reason_id = (
                        result.get("number_exclusion_reason", "")
                        or result.get("exclusion_reason_id", "")
                    )

                # ── 最终纳入文献：清除排除理由字段 ──────────────────────────
                if include_or_not == 'yes':
                    exclusion_reason = ''
                    exclusion_reason_id = ''

                xml_fields = self._load_xml_fields(source_xml) if source_xml else {}

                # ── 自定义提取字段（从 JSON extracted_fields 读取）──────────
                extracted = result.get("extracted_fields", {})
                if not isinstance(extracted, dict):
                    extracted = {}

                row = {
                    "id": idx,
                    "include_or_not": include_or_not,
                    "manual_override": manual_override_val,
                    "exclusion_reason_id": exclusion_reason_id,
                    "exclusion_reason": exclusion_reason,
                    "ReferenceType": xml_fields.get("ReferenceType", result.get("reference_type", "")),
                    "Title": xml_fields.get("Title", "") or result.get("title", ""),
                    "Author": xml_fields.get("Author", "") or result.get("authors", ""),
                    "Year": xml_fields.get("Year", "") or result.get("year", ""),
                    "Journal": xml_fields.get("Journal", "") or result.get("journal", ""),
                    "Volume": xml_fields.get("Volume", result.get("volume", "")),
                    "Issue": xml_fields.get("Issue", result.get("issue", "")),
                    "Page": xml_fields.get("Page", result.get("page", "")),
                    "Date": xml_fields.get("Date", result.get("date", "")),
                    "Doi": xml_fields.get("Doi", "") or result.get("doi", ""),
                    "PMCID": xml_fields.get("PMCID", result.get("pmcid", "")),
                    "Abstract": xml_fields.get("Abstract", "") or result.get("abstract", ""),
                    "URL": xml_fields.get("URL", "") or result.get("url", ""),
                    "Address": xml_fields.get("Address", result.get("address", "")),
                    "source_xml": source_xml,
                }
                for fn in extraction_field_names:
                    row[fn] = extracted.get(fn, "")
                rows.append(row)

            df = pd.DataFrame(rows)
            for h in headers:
                if h not in df.columns:
                    df[h] = None
            df = df.reindex(columns=headers)

            excel_name = f"screening_results_{export_type}_{model_suffix}_{ts}.xlsx"
            excel_path = self.workspace / excel_name
            df.to_excel(excel_path, index=False, engine='openpyxl')
            self.logger.info(f"[导出] 生成Excel ({export_type}): {len(rows)} 行")
            return excel_path

        except ImportError:
            self.logger.warning("[警告] pandas 未安装，跳过 Excel 生成")
        except Exception as e:
            self.logger.error(f"[错误] 生成 Excel 失败: {e}")
        return None
