"""
结果归纳步骤 Handler

负责：
- 获取 ai_screen 步骤输出的 JSON 结果
- 合并人工审阅（ManualReview）覆写 —— 人工决定 > AI 共识
- 按 export_type（all/included/excluded）过滤
- 生成 Excel 和 RIS 文件
- 保存产物到 DataFile

多模型说明：
- 文件命名：使用所有参与模型的简称拼接，单模型保留原来的模型名
- exclusion_reason_id / exclusion_reason：
    1. 人工审阅过 → 使用 ManualReview.reason（纯文本，reason_id 置空）
    2. AI 共识排除 → 使用 number_exclusion_reason / exclusion_reason（JSON 里的合并结果）
- manual_override：ManualReview.is_override=True 时填 'yes'，否则 'no'
- extracted_fields：从 JSON 的 extracted_fields 读取（ai_screen_handler 在多模型时已合并）
"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import logging
logger = logging.getLogger(__name__)

from core.models import DataFile
from core.executors.registry import register
from core.executors.handlers.base_handler import BaseStepHandler


def _lookup_criteria_id(reason_text: str, criteria_list: List[str]) -> str:
    """
    通过理由文本在纳排标准列表中查找对应编号（1-based）。
    - 精确匹配优先
    - 其次检查是否包含关系（reason 包含 criteria 文本，或反之）
    - 找不到返回空字符串
    """
    if not reason_text or not criteria_list:
        return ''
    text = reason_text.strip()
    for i, c in enumerate(criteria_list, 1):
        if c.strip() == text:
            return str(i)
    # 模糊匹配：理由文本包含某条标准的内容（或反之）
    for i, c in enumerate(criteria_list, 1):
        c_stripped = c.strip()
        if c_stripped and (c_stripped in text or text in c_stripped):
            return str(i)
    return ''


@register("export")
class ExportHandler(BaseStepHandler):
    """结果归纳步骤 Handler（同步执行）"""

    execution_mode = "sync"

    def execute(self) -> bool:
        """
        导出流程：
        1. 获取 ai_screen 输出的 JSON 结果
        2. 按 export_type 过滤
        3. 生成 Excel
        4. 生成 RIS（仅 included 条目）
        5. 保存产物
        """
        self.logger.info("[步骤] 开始结果归纳...")
        export_type = self.config.get("export_type", "all")
        self.logger.info(f"[导出] 导出类型: {export_type}")

        # 1. 获取 ai_screen 步骤输出
        ai_step = self.executor.get_previous_step("ai_screen")
        if not ai_step:
            self.logger.error("[错误] 未找到 ai_screen 步骤")
            return False

        result_files = DataFile.objects.filter(
            project=self.project_obj,
            step=ai_step,
            data_category='output',
            description='AI筛选结果',
        )
        self.logger.info(f"[输入] 找到 {result_files.count()} 个结果文件")
        if result_files.count() == 0:
            self.logger.warning("[警告] 没有筛选结果，将生成空报告")

        # 2. 读取并过滤
        final_results = []
        for df in result_files:
            try:
                with open(df.file.path, 'r', encoding='utf-8') as f:
                    final_results.append(json.load(f))
            except Exception as e:
                self.logger.warning(f"[警告] 读取 {df.filename} 失败: {e}")

        self.logger.info(f"[聚合] 有效结果: {len(final_results)} 个")

        # 3. 加载人工审阅覆写记录（source_xml → ManualReview）
        from core.models import ManualReview
        manual_reviews = {
            mr.source_xml: mr
            for mr in ManualReview.objects.filter(project=self.project_obj)
        }
        self.logger.info(f"[人工审阅] 覆写记录: {len(manual_reviews)} 条")

        # 加载 criteria 列表，用于人工审阅时反查排除标准编号
        criteria_list = self._load_criteria_list()
        self.logger.info(f"[导出] 纳排标准条数: {len(criteria_list)}")

        def _final_decision(r: Dict) -> str:
            """返回最终决定：人工决定（included/excluded）优先于 AI 共识。"""
            source_xml = r.get('source_xml', '')
            mr = manual_reviews.get(source_xml)
            if mr and mr.decision in ('included', 'excluded'):
                return mr.decision
            # fallback: AI 共识
            consensus = r.get('consensus') or r.get('decision', '')
            if consensus in ('included', 'excluded', 'conflict'):
                return consensus
            v = r.get('include_or_not', '')
            if v:
                return 'included' if v.lower() == 'yes' else 'excluded'
            return 'pending'

        def _is_included(r: Dict) -> bool:
            return _final_decision(r) == 'included'

        if export_type == "included":
            filtered = [r for r in final_results if _is_included(r)]
        elif export_type == "excluded":
            filtered = [r for r in final_results if not _is_included(r)]
        else:
            filtered = final_results
        self.logger.info(f"[过滤] {export_type} → {len(filtered)} 条")

        model_suffix = self._get_model_suffix()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 5. 生成 Excel（将 manual_reviews + criteria_list 显式传入，避免闭包问题）
        excel_path = self._generate_excel(filtered, export_type, model_suffix, ts, manual_reviews, criteria_list)

        # 5. 生成 RIS（只含 included）
        included = [r for r in filtered if _is_included(r)]
        ris_path = self._generate_ris(included, model_suffix, ts) if included else None

        # 6. 保存产物
        if excel_path and excel_path.exists():
            self.save_output_file(excel_path, excel_path.name, "初筛结果Excel", "output")
        if ris_path and ris_path.exists():
            self.save_output_file(ris_path, ris_path.name, "初筛结果RIS", "output")

        # 7. 更新步骤元数据
        included_count = len([r for r in final_results if _is_included(r)])
        self.step_obj.metadata = {
            "total_results": len(final_results),
            "included_count": included_count,
            "excluded_count": len(final_results) - included_count,
            "manual_override_count": sum(1 for mr in manual_reviews.values() if mr.is_override),
            "completion_time": datetime.now().isoformat(),
        }
        return True

    # ── 私有方法 ─────────────────────────────────────────────────────────

    def _get_model_suffix(self) -> str:
        """
        读取本次 ai_screen 任务使用的模型列表，返回文件名后缀。
        - 单模型 → 模型显示名称（如 deepseek-chat）
        - 多模型 → 各模型名简写拼接（如 ds-chat+gpt4o），超过 40 字符则用 "Nmodels"
        - 兜底   → 'default'
        """
        # 优先从 export 任务自带 config 中读
        model_ids: List[str] = self.config.get("ai_models") or []
        if not model_ids:
            single = self.config.get("ai_model", "")
            if single:
                model_ids = [single]

        # 其次从最近的 ai_screen 任务配置读（注意 DB 存储的是 'ai_screen'，非 'ai_screening'）
        if not model_ids:
            from core.models import Task
            ai_task = Task.objects.filter(
                project=self.project_obj,
                task_type='ai_screen',
            ).order_by('-created_at').first()
            if ai_task and ai_task.config:
                model_ids = ai_task.config.get("ai_models") or []
                if not model_ids:
                    single = ai_task.config.get("ai_model", "")
                    if single:
                        model_ids = [single]

        if not model_ids:
            return "default"

        # 将 model_id 转换为显示名
        try:
            from core.services.ai_models_config import get_models_for_frontend
            id_to_name = {m["id"]: m["name"] for m in get_models_for_frontend()}
        except Exception:
            id_to_name = {}

        display_names = []
        for mid in model_ids:
            name = id_to_name.get(mid, mid)
            # 简化：去掉常见冗余前缀/后缀
            short = (name.replace("deepseek-", "ds-")
                        .replace("gpt-", "gpt")
                        .replace("-preview", "")
                        .replace(" ", "_"))
            display_names.append(short)

        if len(display_names) == 1:
            return display_names[0]

        joined = "+".join(display_names)
        if len(joined) > 40:
            joined = f"{len(display_names)}models"
        return joined

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

                # ── 最终纳排决定（人工 > AI）──────────────────────────────
                if mr and mr.decision in ('included', 'excluded'):
                    include_or_not = 'yes' if mr.decision == 'included' else 'no'
                    manual_override_val = 'yes' if mr.is_override else 'no'
                else:
                    ai_dec = result.get('include_or_not', '')
                    if not ai_dec:
                        ai_dec = 'yes' if result.get('decision') == 'included' else 'no'
                    include_or_not = ai_dec
                    manual_override_val = 'no'

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

                    f.write("ER  - \n\n")

            self.logger.info(f"[导出] 生成 RIS: {len(results)} 条")
            return ris_path
        except Exception as e:
            self.logger.error(f"[错误] 生成 RIS 失败: {e}")
            return None

    def _load_criteria_list(self) -> List[str]:
        """从 criteria 步骤元数据中加载纳排标准列表（按序），供导出时反查编号。"""
        try:
            from core.models import StageStep
            criteria_step = StageStep.objects.filter(
                stage__project_id=self.project_id,
                stage__stage_key='SCREEN_1',
                step_key='criteria',
            ).first()
            if criteria_step and criteria_step.metadata:
                criteria = criteria_step.metadata.get('criteria', [])
                if criteria:
                    return [str(c) for c in criteria]
        except Exception as e:
            logger.warning(f"[导出] 加载纳排标准失败: {e}")
        return []

    def _load_extraction_field_names(self) -> List[str]:
        try:
            from core.models import StageStep
            fe_step = StageStep.objects.filter(
                stage__project_id=self.project_id,
                stage__stage_key='SCREEN_1',
                step_key='field_extraction',
            ).first()
            if fe_step and fe_step.metadata and fe_step.metadata.get('fields'):
                return [f['name'] for f in fe_step.metadata['fields']]
        except Exception as e:
            logger.warning(f"[导出] 加载提取字段失败: {e}")
        return []

    def _itext(self, elem) -> str:
        """提取 XML 元素的全部文本。"""
        if elem is None:
            return ""
        return "".join(elem.itertext()).strip()

    def _load_xml_fields(self, xml_path: str) -> Dict:
        """从源 XML 文件中读取完整文献元数据（带多级目录模糊查找）。"""
        if not xml_path:
            return {}
        try:
            p = Path(xml_path)
            actual_path: Optional[Path] = p if p.exists() else None
            project_ws = self.workspace.parent  # export_*/parent = project_*

            if actual_path is None:
                xml_name = p.name
                name_prefix = xml_name.rsplit('_', 1)[0] if '_' in xml_name else xml_name
                for search_glob, sub_dirs in [
                    ('dedup_*', ['dedup_xmls']),
                    ('parse_*', ['split_xmls', 'parsed_xmls', 'output']),
                ]:
                    for base_dir in project_ws.glob(search_glob):
                        for sub in sub_dirs:
                            xml_sub = base_dir / sub
                            if not xml_sub.exists():
                                continue
                            exact = xml_sub / xml_name
                            if exact.exists():
                                actual_path = exact
                                break
                            for f in xml_sub.glob(f'*{name_prefix}*'):
                                actual_path = f
                                break
                            if actual_path:
                                break
                        if actual_path:
                            break
                    if actual_path:
                        break

            if actual_path is None:
                self.logger.debug(f"[XML] 未找到文件: {xml_path}")
                return {}

            root = ET.parse(actual_path).getroot()
            ref = root
            if root.tag not in ("Reference", "reference"):
                ref = root.find(".//Reference") or root.find(".//reference") or root
            return {
                "ReferenceType": self._itext(ref.find("ReferenceType")),
                "Title":         self._itext(ref.find("Title")),
                "Author":        self._itext(ref.find("Authors")) or self._itext(ref.find("Author")),
                "Year":          self._itext(ref.find("Year")),
                "Journal":       self._itext(ref.find("Journal")),
                "Volume":        self._itext(ref.find("Volume")),
                "Issue":         self._itext(ref.find("Issue")),
                "Page":          self._itext(ref.find("Page")),
                "Date":          self._itext(ref.find("Date")),
                "Doi":           self._itext(ref.find("Doi")) or self._itext(ref.find("DOI")),
                "PMCID":         self._itext(ref.find("PMCID")),
                "Abstract":      self._itext(ref.find("Abstract")),
                "URL":           self._itext(ref.find("Url")) or self._itext(ref.find("URL")),
                "Address":       self._itext(ref.find("Address")),
            }
        except Exception as e:
            self.logger.warning(f"[警告] 加载 XML 字段失败 {xml_path}: {e}")
            return {}
