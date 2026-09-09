"""Excel exporter for resolved screening results."""

from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from core.screening.services.decision_service import ScreeningDecisionService
from core.screening.exporters.common import _lookup_criteria_id, format_conflict_detail


class ScreeningExcelExporter:
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def _generate_excel(self, results: Iterable[Dict], export_type: str,
                        model_suffix: str, ts: str,
                        manual_reviews: Dict,
                        criteria_list: List[str] = None,
                        on_record: Optional[Callable] = None) -> Optional[Path]:
        """生成 Excel 文件，返回文件路径；失败返回 None。

        Args:
            manual_reviews:  source_xml → ManualReview 对象的映射，显式传入避免闭包问题。
            criteria_list:   纳排标准文本列表（按序），用于人工理由反查编号。
        """
        if criteria_list is None:
            criteria_list = []
        try:
            from openpyxl import Workbook

            headers = [
                "id", "include_or_not", "manual_override", "exclusion_reason_id", "exclusion_reason",
                "ReferenceType", "Title", "Author", "Year", "Journal",
                "Volume", "Issue", "Page", "Date", "Doi", "PMCID", "Abstract", "URL", "Address",
                "source_xml",
            ]
            # 追加自定义提取字段
            extraction_field_names = self._load_extraction_field_names()
            headers.extend(extraction_field_names)

            excel_name = f"screening_results_{export_type}_{model_suffix}_{ts}.xlsx"
            excel_path = self.workspace / excel_name
            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet('screening_results')
            sheet.append(headers)

            row_count = 0
            for result in results:
                source_xml = result.get("source_xml", "")
                mr = result.get('_export_manual_review') or manual_reviews.get(source_xml)

                # ── 最终纳排决定（与 QA 导入共用同一领域规则）──────────────
                final_decision = result.get('_export_final_decision') or ScreeningDecisionService.resolve(result, mr)
                if final_decision == 'included':
                    include_or_not = 'yes'
                elif final_decision == 'conflict':
                    # 复用现有字段明确标记豁免导出的 AI 分歧，不新增 Excel 列。
                    include_or_not = 'conflict'
                else:
                    include_or_not = 'no'
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

                if final_decision == 'conflict':
                    exclusion_reason_id = ''
                    exclusion_reason = format_conflict_detail(result)

                # ── 最终纳入文献：清除排除理由字段 ──────────────────────────
                if include_or_not == 'yes':
                    exclusion_reason = ''
                    exclusion_reason_id = ''

                xml_fields = result.get('_export_xml_fields')
                if xml_fields is None:
                    xml_fields = self._load_xml_fields(source_xml) if source_xml else {}

                # ── 自定义提取字段（从 JSON extracted_fields 读取）──────────
                extracted = result.get("extracted_fields", {})
                if not isinstance(extracted, dict):
                    extracted = {}

                # RIS 与 Excel 的筛选相互独立。仅为 RIS 传入的分歧记录不写 Excel。
                include_in_excel = result.get('_export_include_excel', True)
                if on_record is not None:
                    on_record(result, xml_fields, final_decision)
                if not include_in_excel:
                    continue

                row = {
                    "id": row_count + 1,
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
                sheet.append([row.get(header, '') for header in headers])
                row_count += 1

            workbook.save(excel_path)
            self.logger.info(f"[导出] 生成Excel ({export_type}): {row_count} 行")
            return excel_path

        except ImportError:
            self.logger.warning("[警告] openpyxl 未安装，跳过 Excel 生成")
        except Exception as e:
            self.logger.error(f"[错误] 生成 Excel 失败: {e}")
        return None
