import json
import re
import os


def extract_and_format_json(json_file_path):
    """
    从JSON文件中提取prompt1_result, prompt2_result, prompt3_result
    并格式化JSON内容
    """
    # 读取JSON文件
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 提取并格式化三个结果
    formatted_results = {}
    if "pdf_file" in data:
        formatted_results["pdf_file"] = data["pdf_file"]

    for key in ['prompt1_result']:
        if key in data['results']:
            # 提取JSON内容（去除可能存在的```json标记）
            content = data['results'][key]

            # 检查内容是否为纯文本而非JSON格式
            if not content.strip().startswith(('{', '[')) and '```json' not in content:
                # 如果是纯文本，直接忽略（跳过当前key的处理）
                print(f"跳过键 '{key}'，因为其内容是纯文本")
                continue

            # 使用正则表达式提取JSON部分
            json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
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
                else:
                    # 空内容也忽略
                    print(f"跳过键 '{key}'，因为其内容是空的")
                    continue
            except json.JSONDecodeError as e:
                # JSON解析失败也忽略
                print(f"解析 <<{filename}>> | '{key}' 时出错: {e}")
                print(f"问题内容: {json_content[:200]}...")
                continue  # 跳过这个键
    return formatted_results


def traverse_directory(path):
    file_pathes = []
    for root, dirs, files in os.walk(path):
        files.sort()
        for file in files:
            if re.search(r'\.json$', file, re.IGNORECASE):
                file_path = os.path.join(root, file)
                file_pathes.append(file_path)
    return file_pathes


if __name__ == "__main__":
    #os.chdir(__file__ + '/../..')
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # print(os.getcwd())
    files = traverse_directory('1/results')
    for file in files:
        assert isinstance(file, str)
        filename = file.split('/')[2]
        results = extract_and_format_json(file)

        with open(f'2/results/{filename}.json', 'w', encoding='utf-8') as file:
            json.dump(results, file, ensure_ascii=False, indent=2)
