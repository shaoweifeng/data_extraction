"""
AI筛选脚本 - 纯净版

提供AI API调用功能：
- screen_entry(): 筛选单篇文献
- screen_batch(): 批量筛选文献
- parse_ai_response(): 解析AI返回的JSON

设计原则：
- 纯函数式，无副作用
- 无数据库操作
- 无状态管理（由调用者传入已处理列表）
- 支持配置化（API endpoint、密钥等）

依赖：
- requests: HTTP请求
"""

import json
import re
import time
import requests
from typing import List, Dict, Optional, Tuple
from datetime import datetime


# ============================================================================
# 配置常量
# ============================================================================

DEFAULT_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 120
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TEMPERATURE = 0.1
DEFAULT_RETRY_DELAY = 5
DEFAULT_MAX_RETRIES = 3


# ============================================================================
# AI API调用
# ============================================================================

def call_ai_api(
    prompt: str,
    content: str,
    api_url: str = DEFAULT_API_URL,
    api_key: str = None,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE
) -> Optional[str]:
    """
    调用AI API进行筛选
    
    Args:
        prompt: 提示词
        content: 待分析内容（标题+摘要）
        api_url: API端点
        api_key: API密钥
        model: 模型名称
        timeout: 超时时间（秒）
        max_tokens: 最大token数
        temperature: 温度参数
    
    Returns:
        AI返回的文本，失败返回None
    """
    if not api_key:
        raise ValueError("API密钥未设置")
    
    # 截断超长内容（避免超出token限制）
    if len(content) > 100000:
        content = content[:100000] + "\n\n[内容已截断...]"
    
    # 构建完整提示
    full_prompt = f"{prompt}\n\n[文献内容]\n{content}"
    
    # 构建请求数据
    data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": full_prompt
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    
    # 请求头
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(
            api_url,
            headers=headers,
            json=data,
            timeout=timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            print(f"[API错误] {response.status_code}: {response.text}")
            return None
    
    except requests.Timeout:
        print("[API超时] 请求超时")
        return None
    
    except Exception as e:
        print(f"[API异常] {str(e)}")
        return None


def call_ai_api_with_retry(
    prompt: str,
    content: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: int = DEFAULT_RETRY_DELAY,
    **kwargs
) -> Tuple[Optional[str], int]:
    """
    带重试的AI API调用
    
    Args:
        prompt: 提示词
        content: 待分析内容
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        **kwargs: 其他参数传给call_ai_api
    
    Returns:
        (AI返回文本, 实际重试次数)
    """
    retry_count = 0
    
    while retry_count <= max_retries:
        result = call_ai_api(prompt, content, **kwargs)
        
        if result is not None:
            return (result, retry_count)
        
        retry_count += 1
        
        if retry_count <= max_retries:
            print(f"[重试] {retry_count}/{max_retries}，等待{retry_delay}秒...")
            time.sleep(retry_delay)
    
    return (None, retry_count)


# ============================================================================
# AI响应解析
# ============================================================================

def parse_ai_response(response_text: str) -> Dict:
    """
    解析AI返回的JSON
    
    Args:
        response_text: AI返回的原始文本
    
    Returns:
        解析后的字典，包含decision/confidence/reasoning等字段
    """
    if not response_text:
        return {
            "decision": "error",
            "confidence": 0.0,
            "reasoning": "AI返回空响应",
            "raw_response": None
        }
    
    try:
        # 清理Markdown代码块标记
        cleaned = response_text.strip()
        
        if cleaned.startswith('```json'):
            cleaned = cleaned[7:]
        elif cleaned.startswith('```'):
            cleaned = cleaned[3:]
        
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]
        
        cleaned = cleaned.strip()
        
        # 解析JSON
        parsed = json.loads(cleaned)
        
        # 处理不同格式
        if isinstance(parsed, list) and len(parsed) > 0:
            result = parsed[0]
        elif isinstance(parsed, dict):
            result = parsed
        else:
            result = {}
        
        # 标准化字段名
        return {
            "decision": result.get("decision") or result.get("include_or_not") or "unknown",
            "confidence": float(result.get("confidence", 0.0)),
            "reasoning": result.get("reasoning") or result.get("exclusion_reason") or "",
            "exclusion_reason_id": result.get("exclusion_reason_id") or result.get("number_exclusion_reason"),
            "raw_response": parsed
        }
    
    except json.JSONDecodeError as e:
        # 尝试正则提取决策
        decision_match = re.search(r'"(?:decision|include_or_not)"\s*:\s*"([^"]+)"', response_text)
        decision = decision_match.group(1) if decision_match else "parse_error"
        
        return {
            "decision": decision,
            "confidence": 0.0,
            "reasoning": f"JSON解析失败: {str(e)}",
            "raw_response": response_text
        }


# ============================================================================
# 筛选函数
# ============================================================================

def screen_entry(
    entry: Dict,
    criteria: List[str],
    prompt_template: str = None,
    **api_kwargs
) -> Dict:
    """
    筛选单篇文献
    
    Args:
        entry: 文献条目字典（包含title/abstract等）
        criteria: 纳排标准列表
        prompt_template: 自定义提示词模板（可选）
        **api_kwargs: API调用参数
    
    Returns:
        合并后的结果字典（包含原文信息+AI筛选结论）
    """
    # 默认提示词模板
    if not prompt_template:
        prompt_template = """你是一位专业的文献筛选助手，请根据以下纳排标准判断文献是否应该纳入：

筛选标准：
{criteria}

请返回JSON格式：
[{
    "decision": "included" 或 "excluded",
    "confidence": 0.0-1.0,
    "reasoning": "判断理由"
}]
"""
    
    # 构建提示词
    criteria_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(criteria))
    prompt = prompt_template.replace("{screening_criteria}", criteria_text)
    
    # 构建内容
    title = entry.get("title", "")
    abstract = entry.get("abstract", "")
    content = f"标题: {title}\n\n摘要: {abstract}"
    
    # 调用AI API（带重试）
    response, retries = call_ai_api_with_retry(prompt, content, **api_kwargs)
    
    # 解析响应
    ai_result = parse_ai_response(response)
    
    # 合并原文信息与AI结论
    return {
        # 原文信息
        "title": title,
        "authors": entry.get("authors", []),
        "year": entry.get("year"),
        "journal": entry.get("journal"),
        "doi": entry.get("doi"),
        "url": entry.get("url"),
        "abstract": abstract,
        "source_xml": entry.get("source_xml", ""),
        
        # AI筛选结论
        "decision": ai_result["decision"],
        "confidence": ai_result["confidence"],
        "reasoning": ai_result["reasoning"],
        "exclusion_reason_id": ai_result.get("exclusion_reason_id"),
        
        # 元数据
        "timestamp": datetime.now().isoformat(),
        "model": api_kwargs.get("model", DEFAULT_MODEL),
        "retries": retries
    }


def screen_batch(
    entries: List[Dict],
    criteria: List[str],
    batch_size: int = 10,
    concurrency: int = 3,
    progress_callback=None,
    should_stop=None,
    **api_kwargs
) -> List[Dict]:
    """
    批量筛选文献
    
    Args:
        entries: 文献条目列表
        criteria: 纳排标准列表
        batch_size: 批处理大小（暂未使用，为未来优化预留）
        concurrency: 并发数（暂未使用，为未来优化预留）
        progress_callback: 进度回调函数 (current, total, result)
        should_stop: 停止信号检测函数
        **api_kwargs: API调用参数
    
    Returns:
        结果字典列表
    """
    results = []
    total = len(entries)
    
    for i, entry in enumerate(entries, start=1):
        # 检查停止信号
        if should_stop and should_stop():
            print(f"[停止] 收到停止信号，已处理 {i-1}/{total} 篇")
            break
        
        # 筛选单篇
        result = screen_entry(entry, criteria, **api_kwargs)
        results.append(result)
        
        # 进度回调
        if progress_callback:
            progress_callback(i, total, result)
        
        # 避免API限流（简单延迟）
        time.sleep(0.5)
    
    return results


# ============================================================================
# 辅助函数
# ============================================================================

def build_screening_prompt(criteria: List[str], custom_prompt: str = None) -> str:
    """
    构建筛选提示词
    
    Args:
        criteria: 纳排标准列表
        custom_prompt: 自定义提示词模板（可选）
    
    Returns:
        完整的提示词字符串
    """
    if custom_prompt:
        # 替换占位符
        criteria_text = "\n".join(f"- {c}" for c in criteria)
        return custom_prompt.replace("{screening_criteria}", criteria_text)
    
    # 默认模板
    return f"""你是一位专业的文献筛选助手，请根据以下纳排标准判断文献是否应该纳入：

筛选标准：
{chr(10).join(f'{i+1}. {c}' for i, c in enumerate(criteria))}

请返回JSON格式：
[{
    "decision": "included" 或 "excluded",
    "confidence": 0.0-1.0,
    "reasoning": "判断理由"
}]

注意：
- 如果文献标题或摘要中明确包含排除标准关键词，请判定为 excluded
- 只有在完全符合纳入标准时才判定为 included
- confidence 表示你对判断的信心程度
"""


def validate_criteria(criteria: List[str]) -> Tuple[bool, str]:
    """
    验证纳排标准格式
    
    Args:
        criteria: 纳排标准列表
    
    Returns:
        (是否有效, 错误信息)
    """
    if not criteria:
        return (False, "纳排标准不能为空")
    
    if len(criteria) < 2:
        return (False, "纳排标准至少需要2条")
    
    for i, c in enumerate(criteria):
        if not c or not c.strip():
            return (False, f"第{i+1}条标准为空")
        
        if len(c) > 200:
            return (False, f"第{i+1}条标准过长（超过200字符）")
    
    return (True, "验证通过")


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    # 测试示例
    test_entry = {
        "title": "Efficacy of immunotherapy in lung cancer treatment",
        "abstract": "This study investigates the efficacy of immunotherapy...",
        "authors": ["Smith J", "Doe A"],
        "year": "2023",
        "journal": "Cancer Research"
    }
    
    test_criteria = [
        "排除非英文文献",
        "排除动物实验研究",
        "排除病例报告",
        "仅纳入临床研究"
    ]
    
    # 验证标准
    valid, msg = validate_criteria(test_criteria)
    print(f"标准验证: {valid} - {msg}")
    
    # 构建提示词
    prompt = build_screening_prompt(test_criteria)
    print(f"\n提示词:\n{prompt[:200]}...")
    
    # 注意：实际调用需要API密钥
    print("\n[提示] 请设置API密钥后调用 screen_entry() 进行实际筛选")
