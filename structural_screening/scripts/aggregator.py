"""
结果聚合脚本 - 纯净版

提供AI筛选结果的聚合和导出功能：
- aggregate_results(): 扫描目录，收集所有JSON结果
- export_excel(): 导出为Excel文件
- export_ris(): 导出为RIS格式（EndNote）

设计原则：
- 纯函数式，无副作用
- 无数据库操作
- 无全局状态（移除原来的 all_df 和 _xml_cache）
- 自动去重（每目录只取最新的JSON）

关键修复：
- 修复了之前 aggregator.py 中每目录多个JSON导致重复的问题
- 现在每个结果目录只取mtime最新的一个JSON文件
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import rispy
except ImportError:
    rispy = None


# ============================================================================
# 遍历和收集
# ============================================================================

def traverse_results_directory(results_dir: str) -> List[str]:
    """
    遍历结果目录，收集所有JSON文件
    
    Args:
        results_dir: 结果目录路径
    
    Returns:
        JSON文件路径列表
    """
    json_files = []
    
    for root, dirs, files in os.walk(results_dir):
        for file in files:
            if file.lower().endswith('.json'):
                json_files.append(os.path.join(root, file))
    
    return json_files


def collect_latest_results(results_dir: str) -> List[Dict]:
    """
    收集每个结果目录中的最新JSON（修复重复问题）
    
    问题背景：
    之前 aggregator 会收集目录下的所有 JSON，如果一个目录里有多个 JSON
    （例如多次运行、重试遗留），会导致重复聚合。
    
    解决方案：
    按目录分组，每个目录只取 mtime 最新的一个 JSON 文件。
    
    Args:
        results_dir: 结果目录路径
    
    Returns:
        解析后的结果字典列表（每目录一个）
    """
    # 按目录分组
    dir_files = defaultdict(list)
    
    for root, dirs, files in os.walk(results_dir):
        for file in files:
            if file.lower().endswith('.json'):
                filepath = os.path.join(root, file)
                dir_files[root].append(filepath)
    
    # 每个目录只取最新的
    latest_results = []
    
    for dir_path, files in dir_files.items():
        if not files:
            continue
        
        # 按 mtime 排序
        files_with_mtime = [
            (f, os.path.getmtime(f))
            for f in files
        ]
        files_with_mtime.sort(key=lambda x: x[1], reverse=True)
        
        # 取最新的文件
        latest_file = files_with_mtime[0][0]
        
        try:
            with open(latest_file, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
                
                # 添加元数据
                data['_source_file'] = latest_file
                data['_source_dir'] = dir_path
                
                latest_results.append(data)
        
        except Exception as e:
            print(f"[警告] 读取 {latest_file} 失败: {e}")
    
    return latest_results


# ============================================================================
# 数据标准化
# ============================================================================

def normalize_result(data: Dict) -> Dict:
    """
    将各种格式的AI结果标准化为统一结构
    
    支持格式：
    1. 嵌套格式: {prompt1_result: [{...}]}
    2. 扁平格式: {include_or_not: "included", ...}
    3. 混合格式: {title: "...", authors: [...], decision: "..."}
    
    Args:
        data: 原始数据字典
    
    Returns:
        标准化后的字典
    """
    # 字段映射表
    field_mapping = {
        # 标题
        'title': 'Title',
        
        # 作者
        'authors': 'Author',
        'first_author': 'Author',
        'author': 'Author',
        
        # 年份
        'year': 'Year',
        'public_year': 'Year',
        
        # 期刊
        'journal': 'Journal',
        'journal_name': 'Journal',
        
        # 其他字段
        'volume': 'Volume',
        'issue': 'Issue',
        'page': 'Page',
        'pages': 'Page',
        'doi': 'Doi',
        'url': 'URL',
        'abstract': 'Abstract',
        'extracted_abstract': 'Abstract',
        
        # AI筛选结论
        'include_or_not': 'decision',
        'decision': 'decision',
        'exclusion_reason': 'reasoning',
        'reasoning': 'reasoning',
        'exclusion_reason_id': 'exclusion_reason_id',
        'number_exclusion_reason': 'exclusion_reason_id',
        
        # 源文件
        'source_xml': 'source_xml',
        'file_path': 'source_xml',
        'pdf_file': 'source_xml'
    }
    
    # 尝试提取 prompt1_result（嵌套格式）
    prompt1_data = data.get('prompt1_result', [])
    
    if prompt1_data:
        # 取第一个元素
        base_info = prompt1_data[0] if isinstance(prompt1_data, list) else prompt1_data
    else:
        # 扁平格式
        base_info = data
    
    # 应用字段映射
    normalized = {}
    
    for key, value in base_info.items():
        mapped_key = field_mapping.get(key, key)
        
        # 处理列表字段（如 authors）
        if isinstance(value, list):
            try:
                value = ", ".join(str(v) for v in value)
            except:
                pass
        
        normalized[mapped_key] = value
    
    # 确保必要字段存在
    if 'Title' not in normalized:
        normalized['Title'] = data.get('title', 'N/A')
    
    if 'decision' not in normalized:
        # 尝试从外层获取
        normalized['decision'] = data.get('include_or_not') or data.get('decision') or 'unknown'
    
    if 'reasoning' not in normalized:
        normalized['reasoning'] = data.get('exclusion_reason') or data.get('reasoning') or ''
    
    # 添加原始来源信息
    normalized['_source_file'] = data.get('_source_file', '')
    
    return normalized


# ============================================================================
# Excel 导出
# ============================================================================

def export_excel(
    results: List[Dict],
    output_path: str,
    headers: Optional[List[str]] = None
) -> bool:
    """
    将结果导出为Excel文件
    
    Args:
        results: 结果字典列表
        output_path: 输出文件路径
        headers: 自定义表头顺序（可选）
    
    Returns:
        True if 成功, False otherwise
    """
    if pd is None:
        print("[错误] pandas 未安装，请运行: pip install pandas openpyxl")
        return False
    
    if not results:
        print("[警告] 没有结果可导出")
        return False
    
    # 标准化所有结果
    normalized_results = [normalize_result(r) for r in results]
    
    # 默认表头顺序
    if not headers:
        headers = [
            'Title', 'Author', 'Year', 'Journal',
            'Volume', 'Issue', 'Page', 'Doi', 'URL',
            'Abstract',
            'decision', 'confidence', 'reasoning', 'exclusion_reason_id',
            'source_xml'
        ]
    
    # 创建 DataFrame
    df = pd.DataFrame(normalized_results)
    
    # 确保所有表头列存在
    for header in headers:
        if header not in df.columns:
            df[header] = None
    
    # 按表头顺序排列
    df = df.reindex(columns=headers, fill_value=None)
    
    # 导出到Excel
    try:
        df.to_excel(output_path, index=False, engine='openpyxl')
        print(f"[成功] 导出Excel: {output_path} ({len(df)} 行)")
        return True
    
    except Exception as e:
        print(f"[错误] 导出Excel失败: {e}")
        return False


# ============================================================================
# RIS 导出
# ============================================================================

def export_ris(
    results: List[Dict],
    output_path: str,
    filter_included: bool = True
) -> bool:
    """
    将结果导出为RIS格式（EndNote导入）
    
    Args:
        results: 结果字典列表
        output_path: 输出文件路径
        filter_included: 是否只导出纳入的文献
    
    Returns:
        True if 成功, False otherwise
    """
    # 过滤只保留纳入的文献
    if filter_included:
        results = [r for r in results if r.get('decision') == 'included']
    
    if not results:
        print("[警告] 没有纳入的文献可导出")
        return False
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            for r in results:
                normalized = normalize_result(r)
                
                # RIS 格式
                f.write("TY  - JOUR\n")
                f.write(f"TI  - {normalized.get('Title', '')}\n")
                
                # 作者（多行）
                authors = normalized.get('Author', '')
                if isinstance(authors, str):
                    for author in authors.split(','):
                        author = author.strip()
                        if author:
                            f.write(f"AU  - {author}\n")
                
                f.write(f"PY  - {normalized.get('Year', '')}\n")
                f.write(f"JO  - {normalized.get('Journal', '')}\n")
                f.write(f"VL  - {normalized.get('Volume', '')}\n")
                f.write(f"IS  - {normalized.get('Issue', '')}\n")
                f.write(f"SP  - {normalized.get('Page', '')}\n")
                f.write(f"DO  - {normalized.get('Doi', '')}\n")
                f.write(f"UR  - {normalized.get('URL', '')}\n")
                f.write(f"AB  - {normalized.get('Abstract', '')}\n")
                
                # 自定义字段：AI筛选结果
                f.write(f"N1  - AI Decision: {normalized.get('decision', '')}\n")
                f.write(f"N2  - Reasoning: {normalized.get('reasoning', '')}\n")
                
                f.write("ER  - \n\n")
        
        print(f"[成功] 导出RIS: {output_path} ({len(results)} 条)")
        return True
    
    except Exception as e:
        print(f"[错误] 导出RIS失败: {e}")
        return False


# ============================================================================
# 主函数
# ============================================================================

def aggregate_and_export(
    results_dir: str,
    output_dir: str,
    excel_filename: str = "screening_results.xlsx",
    ris_filename: str = "screening_results.ris"
) -> Dict:
    """
    主函数：聚合结果并导出
    
    Args:
        results_dir: AI筛选结果JSON文件所在目录
        output_dir: 输出目录
        excel_filename: Excel文件名
        ris_filename: RIS文件名
    
    Returns:
        统计信息字典
    """
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 收集最新结果
    results = collect_latest_results(results_dir)
    
    print(f"[聚合] 找到 {len(results)} 个有效结果")
    
    # 导出Excel
    excel_path = os.path.join(output_dir, excel_filename)
    excel_success = export_excel(results, excel_path)
    
    # 导出RIS（只包含纳入的文献）
    ris_path = os.path.join(output_dir, ris_filename)
    ris_success = export_ris(results, ris_path, filter_included=True)
    
    # 统计信息
    included_count = len([r for r in results if r.get('decision') == 'included'])
    excluded_count = len([r for r in results if r.get('decision') == 'excluded'])
    unknown_count = len(results) - included_count - excluded_count
    
    return {
        'total_count': len(results),
        'included_count': included_count,
        'excluded_count': excluded_count,
        'unknown_count': unknown_count,
        'excel_success': excel_success,
        'ris_success': ris_success,
        'excel_path': excel_path if excel_success else None,
        'ris_path': ris_path if ris_success else None
    }


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python aggregator.py <结果目录> [输出目录]")
        sys.exit(1)
    
    results_dir = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(results_dir, "aggregated")
    
    result = aggregate_and_export(results_dir, output_dir)
    
    print("\n" + "="*50)
    print("聚合统计:")
    print(f"  总数: {result['total_count']}")
    print(f"  纳入: {result['included_count']}")
    print(f"  排除: {result['excluded_count']}")
    print(f"  未知: {result['unknown_count']}")
    print("="*50)
