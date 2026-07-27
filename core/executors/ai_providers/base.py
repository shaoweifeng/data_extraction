"""
AI Provider 抽象基类

定义统一的文献筛选接口，所有 AI provider 必须实现此接口。
将来支持多模型并发时，每个 provider 独立实例，结果汇总后对有分歧的文献单独标记。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ScreeningResult:
    """
    单篇文献的筛选结果
    
    预留字段说明：
    - model: 用于将来多模型对比时标识是哪个模型的结论
    - raw_response: 保留原始 AI 响应，方便审计和调试
    - confidence: 预留给将来有置信度输出的模型
    """
    title: str
    decision: str                    # "included" | "excluded" | "error"
    exclusion_reason: str = ""       # 排除理由（included 时为空）
    exclusion_criterion_no: str = "" # 违反的标准编号（如 "3"）
    model: str = ""                  # 使用的模型名称
    raw_response: str = ""           # 原始 AI 响应
    extracted_fields: Dict = field(default_factory=dict)  # AI 提取的自定义字段
    confidence: Optional[float] = None  # 置信度（当前模型不输出，预留）
    error: str = ""                  # 出错时的错误信息

    @property
    def is_included(self) -> bool:
        return self.decision == "included"

    @property
    def is_error(self) -> bool:
        return self.decision == "error"

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision,
            "exclusion_reason": self.exclusion_reason,
            "number_exclusion_reason": self.exclusion_criterion_no,
            "include_or_not": "yes" if self.is_included else "no",
            "model": self.model,
            "extracted_fields": self.extracted_fields,
            "confidence": self.confidence,
            "raw_ai_response": self.raw_response,
            "error": self.error,
        }


class BaseAIProvider(ABC):
    """
    AI Provider 抽象基类
    
    子类实现 screen_single() 即可，批处理和并发由框架层（StepExecutor）控制。
    
    将来多模型扩展时：
    1. 新建 xxx_provider.py 继承此类，实现 screen_single()
    2. 在 __init__.py 的 registry 里注册
    3. StepExecutor 可并发调用多个 provider，对结果有分歧的文献单独列出
    """

    def __init__(self, config: dict):
        self.config = config
        self._setup()

    def _setup(self):
        """子类可覆盖，用于初始化客户端、读取 API key 等"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称，如 'deepseek'、'claude'"""
        pass

    @abstractmethod
    def screen_single(self, entry: Dict, criteria: List[str], prompt_template: str) -> ScreeningResult:
        """
        对单篇文献执行 AI 筛选
        
        Args:
            entry: 文献信息字典（title, abstract, authors, journal, year, doi 等）
            criteria: 纳排标准列表
            prompt_template: prompt 模板字符串（含 {screening_criteria} 占位符）
        
        Returns:
            ScreeningResult
        """
        pass

    def screen_batch(self, batch: List[Dict], criteria: List[str], prompt_template: str,
                     concurrency: int = 16) -> List[ScreeningResult]:
        """
        批量筛选（默认使用线程池并发调用 screen_single，子类可覆盖实现真正的批量 API）
        
        Args:
            batch: 文献列表
            criteria: 纳排标准列表
            prompt_template: prompt 模板
            concurrency: 并发线程数（默认16）
        
        Returns:
            ScreeningResult 列表（与 batch 顺序对应）
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: List[Optional[ScreeningResult]] = [None] * len(batch)

        def _screen_one(idx: int, entry: Dict) -> tuple:
            try:
                result = self.screen_single(entry, criteria, prompt_template)
            except Exception as e:
                result = ScreeningResult(
                    title=entry.get("title", ""),
                    decision="error",
                    model=self.name,
                    error=str(e)
                )
            return idx, result

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_screen_one, i, entry): i for i, entry in enumerate(batch)}
            for future in as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        return results
