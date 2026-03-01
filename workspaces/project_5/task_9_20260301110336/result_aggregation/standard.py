import json
import re
import os


def extract_and_format_json(json_file_path):
    """
    从JSON文件中提取 screening_result 并格式化
    """
    try:
        # 读取JSON文件
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"读取文件失败 {json_file_path}: {e}")
        return {}

    # 提取 screening_result
    formatted_results = {}
    if "screening_result" in data:
        # 兼容旧逻辑，把它放到 prompt1_result 结构下，以便 aggregator.py 通用处理
        # 或者直接重构 aggregator.py，但为了最小改动，这里做个适配
        formatted_results["prompt1_result"] = [data["screening_result"]]
        formatted_results["pdf_file"] = data["screening_result"].get("source_xml", "")
    
    # 兼容旧的 results 结构
    elif "results" in data:
        # ... (保留原有的处理逻辑)
        for key in ['prompt1_result']:
            if key in data['results']:
                # 提取JSON内容（去除可能存在的```json标记）
                content = data['results'][key]

                # 检查内容是否为纯文本而非JSON格式
                if not isinstance(content, str) or (not content.strip().startswith(('{', '[')) and '```json' not in content):
                    # 如果不是字符串或者是纯文本，直接忽略
                    print(f"跳过键 '{key}'，因为其内容格式不符")
                    continue

                # 使用正则表达式提取JSON部分
                json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
                if json_match:
                    json_content = json_match.group(1)
                else:
                    json_content = content

                # 解析并重新格式化JSON
                try:
                    if json_content.strip():  # 确保不是空字符串
                        json_data = json.loads(json_content)
                        formatted_results[key] = json_data
                except json.JSONDecodeError as e:
                    print(f"解析错误: {e}")
                    continue

    return formatted_results


def traverse_directory(path):
    file_pathes = []
    for root, dirs, files in os.walk(path):
        files.sort()
        for file in files:
            if re.search(r'\.json$', file, re.IGNORECASE) and not file.startswith('error_'):
                file_path = os.path.join(root, file)
                file_pathes.append(file_path)
    return file_pathes


if __name__ == "__main__":
    # 假设当前目录是 result_aggregation
    # 输入目录：../screening_ai/results
    # 输出目录：results
    
    input_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "02_screening_ai", "results")
    output_dir = "results"
    
    # 在 run_extraction_pipeline 中，CWD 已经是 workspace_dir，所以 input_dir 应该是 screening_ai/results
    # 但为了稳健，我们使用相对路径检查
    if not os.path.exists(input_dir) and os.path.exists("screening_ai/results"):
        input_dir = "screening_ai/results"
        
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Standardizing results from {input_dir} to {output_dir}")
    
    files = traverse_directory(input_dir)
    print(f"Found {len(files)} files to standardize")
    
    for file in files:
        filename = os.path.basename(file)
        results = extract_and_format_json(file)
        
        if results:
            with open(os.path.join(output_dir, filename), 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

