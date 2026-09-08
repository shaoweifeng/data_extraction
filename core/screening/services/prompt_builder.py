"""Prompt construction and extraction-field instructions for AI screening."""

from pathlib import Path
from typing import Dict, List

from django.conf import settings


class ScreeningPromptBuilder:
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def _get_prompt_template(self) -> str:
            """读取 prompt 模板（自定义 > prompt1.txt > 内置默认），追加字段提取指令。"""
            try:
                meta = self.project_obj.metadata or {}
                if meta.get('use_custom_prompt') and meta.get('custom_prompt', '').strip():
                    custom = meta['custom_prompt'].strip()
                    if '{screening_criteria}' in custom:
                        self.logger.info("[Prompt] 使用项目自定义 Prompt")
                        return self._append_extraction_block(custom)
                    self.logger.warning("[Prompt] 自定义 Prompt 缺少 {screening_criteria}，回退默认")
            except Exception as e:
                self.logger.warning(f"[Prompt] 读取自定义 Prompt 失败: {e}")

            prompt_path = Path(settings.BASE_DIR) / "core/resources/prompts/prompt1.txt"
            if prompt_path.exists():
                base_prompt = prompt_path.read_text(encoding="utf-8")
            else:
                self.logger.warning(f"[警告] prompt1.txt 不存在，使用内置默认")
                base_prompt = (
                    '你是文献筛选助手，请根据以下排除标准判断文献是否纳入，返回JSON格式：'
                    '[{"exclusion_reason": "", "number_exclusion_reason": "", "include_or_not": "yes"}]\n'
                    '<exclusion_criteria>\n{screening_criteria}\n</exclusion_criteria>'
                )
            return self._append_extraction_block(base_prompt)

    def _append_extraction_block(self, base_prompt: str) -> str:
            fields = self._get_extraction_fields()
            if not fields:
                return base_prompt
            field_descriptions = "\n".join(f'  - "{f["name"]}": {f["definition"]}' for f in fields)
            field_names = ", ".join(f'"{f["name"]}"' for f in fields)
            block = (
                "\n\n=======字段提取任务=======\n"
                "对于纳入的文献，请同时从全文内容中提取以下字段信息：\n"
                f"{field_descriptions}\n\n"
                "输出JSON中的 extracted_fields 字段包含提取结果，格式：\n"
                f'{{"extracted_fields": {{{field_names}: "提取值"}}, ...}}\n\n'
            )
            self.logger.info(f"[字段] 追加提取指令，字段数: {len(fields)}")
            return base_prompt + block

    def _get_extraction_fields(self) -> List[Dict]:
            try:
                fe_step = self.executor.get_previous_step("field_extraction")
                if fe_step and fe_step.metadata:
                    fields = fe_step.metadata.get("fields", [])
                    if fields:
                        self.logger.info(f"[字段] 读取到 {len(fields)} 个提取字段")
                        return fields
            except Exception as e:
                self.logger.warning(f"[字段] 读取提取字段失败: {e}")
            return []

    def _mock_extracted_fields(self) -> Dict:
            return {f["name"]: f"(模拟) {f['definition'][:30]}..." for f in self._get_extraction_fields()}
