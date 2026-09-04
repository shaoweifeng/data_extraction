"""
OpenAI 兼容接口 Provider

参考 xxc/develop 分支 structural_screening/02_screening_ai/screener.py 实现。
使用 OpenAI 兼容接口（/v1/chat/completions），可切换任何兼容格式的模型。

环境变量：
    AI_API_KEY    : API 密钥（必填）
    AI_API_URL    : 接口地址，默认 https://api.deepseek.com/v1
    AI_MODEL      : 模型名称，默认 deepseek-chat
    AI_TIMEOUT    : 单次请求超时秒数，默认 120
"""

import os
import json
import logging
import requests
from typing import List, Dict

from typing import List, Dict, Optional
from .base import BaseAIProvider, ScreeningResult

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(BaseAIProvider):
    """
    OpenAI 兼容接口 Provider（OpenAI 兼容格式）
    
    将来扩展其他模型时，只需新建类继承 BaseAIProvider 并实现 screen_single()。
    """

    def _setup(self):
        self.api_key = (
            self.config.get("api_key")
            or os.environ.get("AI_API_KEY", "")
        )
        self.base_url = (
            self.config.get("api_url")
            or os.environ.get("AI_API_URL", "https://api.deepseek.com/v1")
        ).rstrip("/")
        self.model = (
            self.config.get("model")
            or os.environ.get("AI_MODEL", "deepseek-chat")
        )
        self.timeout = int(
            self.config.get("timeout")
            or os.environ.get("AI_TIMEOUT", "120")
        )
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # 是否为推理模型（思维链模型）：完全依赖配置文件中的 is_reasoning 字段。
        # 不再用模型名关键词猜测，避免误判非 DeepSeek 的 flash/think 命名模型。
        self.is_reasoning: bool = bool(self.config.get("is_reasoning", False))

    @property
    def name(self) -> str:
        return f"openai_compatible/{self.model}"

    def screen_single(self, entry: Dict, criteria: List[str], prompt_template: str) -> ScreeningResult:
        """
        对单篇文献调用 DeepSeek API 执行筛选
        
        Args:
            entry: 文献信息字典
            criteria: 纳排标准列表（每条一个字符串）
            prompt_template: prompt 模板，含 {screening_criteria} 占位符
        
        Returns:
            ScreeningResult（含 token_usage 字段）
        """
        title = entry.get("title", "Unknown")

        # 构建文献内容（Title + Abstract）
        # 摘要不截断：让 AI 读完整摘要，避免因截断导致错误排除
        # （总 prompt 超 100000 字符时会在 _call_api 里整体截断）
        abstract = entry.get("abstract", "")
        
        content = f"Title: {title}\n"
        if abstract:
            content += f"Abstract: {abstract}\n"
        if entry.get("journal"):
            content += f"Journal: {entry['journal']}\n"
        if entry.get("year"):
            content += f"Year: {entry['year']}\n"

        # 注入筛选标准到 prompt
        criteria_text = "\n".join(
            f"{i+1}. {c}" for i, c in enumerate(criteria)
        )
        prompt = prompt_template.replace("{screening_criteria}", criteria_text)
        
        full_prompt = f"{prompt}\n\n[文献内容]\n{content}"

        # 调用 API，同时获取 token 用量
        raw_response, token_usage = self._call_api(full_prompt)
        if raw_response is None:
            return ScreeningResult(
                title=title,
                decision="error",
                model=self.name,
                error="API 调用失败，返回为空",
                token_usage=token_usage,
            )

        # 解析 JSON 响应，携带 token_usage
        result = self._parse_response(title, raw_response)
        result.token_usage = token_usage
        return result

    def _call_api(self, full_prompt: str):
        """
        发送请求到 OpenAI 兼容接口。

        Returns:
            (content: str | None, token_usage: dict | None)
            token_usage 格式：{'prompt': int, 'completion': int, 'total': int}
            API 调用失败或模型不返回 usage 时 token_usage 为 None。
        """
        if not self.api_key:
            raise ValueError("AI_API_KEY 未配置，无法调用真实 AI API")

        # 截断超长内容（API 限制）
        if len(full_prompt) > 100000:
            full_prompt = full_prompt[:100000] + "\n\n[内容已截断...]"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": full_prompt}],
            "temperature": 0.1,
            "max_tokens": 4000,
        }
        # 推理模型（思维链模型）默认在 content 里混入推理过程，
        # 用 thinking.disabled 禁用，使其直接输出结构化 JSON。
        if self.is_reasoning:
            payload["thinking"] = {"type": "disabled"}

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
            if response.status_code == 200:
                body = response.json()
                msg = body["choices"][0]["message"]
                content = msg.get("content") or ""
                # 推理模型（如 deepseek-v4-flash）content 可能为空，
                # 真正的回答在 reasoning_content 里
                if not content.strip():
                    content = msg.get("reasoning_content") or ""
                # 采集 token 用量（OpenAI 兼容接口标准字段）
                raw_usage = body.get("usage") or {}
                token_usage = {
                    "prompt":     raw_usage.get("prompt_tokens", 0),
                    "completion": raw_usage.get("completion_tokens", 0),
                    "total":      raw_usage.get("total_tokens", 0),
                } if raw_usage else None
                if not content.strip():
                    logger.warning("[DeepSeek] 模型返回内容为空（content 和 reasoning_content 均空）")
                    return None, token_usage
                return content, token_usage
            else:
                logger.error(f"[DeepSeek] API 返回错误: {response.status_code} {response.text[:200]}")
                return None, None
        except requests.Timeout:
            logger.error(f"[DeepSeek] 请求超时（{self.timeout}s）")
            return None, None
        except Exception as e:
            logger.error(f"[DeepSeek] 请求异常: {e}")
            return None, None

    def _parse_response(self, title: str, raw: str) -> ScreeningResult:
        """解析 AI 返回的 JSON，生成 ScreeningResult"""
        cleaned = raw.strip()
        # 去除 ```json ... ``` 包裹
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            # AI 返回的是列表（如 [{...}]）或对象（{...}）
            if isinstance(parsed, list) and len(parsed) > 0:
                ai = parsed[0]
            elif isinstance(parsed, dict):
                ai = parsed
            else:
                raise ValueError(f"无法识别的 JSON 格式: {type(parsed)}")

            include_or_not = ai.get("include_or_not", "no").strip().lower()
            decision = "included" if include_or_not == "yes" else "excluded"
            extracted_fields = ai.get("extracted_fields", {})
            if not isinstance(extracted_fields, dict):
                extracted_fields = {}

            return ScreeningResult(
                title=title,
                decision=decision,
                exclusion_reason=ai.get("exclusion_reason", ""),
                exclusion_criterion_no=str(ai.get("number_exclusion_reason", "")),
                model=self.name,
                raw_response=raw,
                extracted_fields=extracted_fields,
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[DeepSeek] JSON 解析失败: {e}, 原始响应: {raw[:200]}")
            return ScreeningResult(
                title=title,
                decision="error",
                model=self.name,
                raw_response=raw,
                error=f"JSON 解析失败: {e}"
            )
