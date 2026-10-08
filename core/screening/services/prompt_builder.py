"""Prompt construction and extraction-field instructions for AI screening."""

import json
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
                    required = ('{screening_criteria}', '{literature_record}')
                    if all(placeholder in custom for placeholder in required):
                        self.logger.info("[Prompt] 使用项目自定义 Prompt")
                        return self._append_extraction_block(custom)
                    self.logger.warning("[Prompt] 自定义 Prompt 缺少必要占位符，回退默认")
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
                    '<exclusion_criteria>\n{screening_criteria}\n</exclusion_criteria>\n'
                    '<literature_record>\n{literature_record}\n</literature_record>'
                )
            return self._append_extraction_block(base_prompt)

    def _append_extraction_block(self, base_prompt: str) -> str:
            fields = self._get_extraction_fields()
            if not fields:
                return base_prompt
            field_specs = []
            seen_names = set()
            for field in fields:
                if not isinstance(field, dict):
                    continue
                name = str(field.get('name') or '').strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                field_specs.append({
                    'name': name,
                    'definition': str(field.get('definition') or '').strip(),
                })
            if not field_specs:
                return base_prompt
            specs_json = json.dumps(field_specs, ensure_ascii=False, indent=2)
            output_example = {
                field['name']: '提取值或空字符串'
                for field in field_specs
            }
            example_json = json.dumps(output_example, ensure_ascii=False, indent=2)
            block = (
                "\n\n<field_extraction_task>\n"
                "本任务已启用额外字段提取。只能根据 <literature_record> 中实际提供的内容提取，"
                "不得联网、猜测或补全。\n"
                "字段定义如下：\n"
                f"{specs_json}\n\n"
                "输出要求：\n"
                "1. 在每个筛选结果对象中增加且仅增加一个 extracted_fields 字段。\n"
                "2. extracted_fields 必须是 JSON 对象，键必须与上述字段名称完全一致，"
                "不得遗漏、改名或增加其他键。\n"
                "3. 文献保留进入下一轮时，按字段定义提取；当前记录没有明确内容时填写空字符串。\n"
                "4. 文献被排除时，extracted_fields 输出空对象 {}，无需执行字段提取。\n"
                "5. 不得改变 exclusion_reason、number_exclusion_reason、include_or_not 三个基础字段。\n"
                "保留文献的 extracted_fields 示例：\n"
                f"{example_json}\n"
                "</field_extraction_task>\n"
            )
            self.logger.info(f"[字段] 追加提取指令，字段数: {len(field_specs)}")
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
