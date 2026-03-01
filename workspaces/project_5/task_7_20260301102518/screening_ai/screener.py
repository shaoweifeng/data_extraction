import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from config import base_url, api_key, max_workers
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


class PDFProcessor:
    def __init__(self):
        self.base_url = base_url
        self.api_key = api_key
        self.max_workers = max_workers
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.processed_log_file = "processed_files.json"
        self.print_lock = threading.Lock()

    def safe_print(self, *args, **kwargs):
        with self.print_lock:
            print(*args, **kwargs)

    def load_processed_files(self):
        """加载已处理文件的记录"""
        try:
            if os.path.exists(self.processed_log_file):
                with open(self.processed_log_file, 'r', encoding='utf-8') as file:
                    return json.load(file)
            return {}
        except Exception as e:
            print(f"加载处理记录失败: {e}")
            return {}

    def save_processed_files(self, processed_files):
        """保存已处理文件的记录"""
        try:
            with open(self.processed_log_file, 'w', encoding='utf-8') as file:
                json.dump(processed_files, file, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存处理记录失败: {e}")

    def mark_file_as_processed(self, pdf_filename, timestamp):
        """标记文件为已处理"""
        with self.print_lock:
            processed_files = self.load_processed_files()
            processed_files[pdf_filename] = {
                "processed_time": timestamp,
                "status": "completed"
            }
            self.save_processed_files(processed_files)

    def is_file_processed(self, pdf_filename):
        """检查文件是否已经处理过"""
        processed_files = self.load_processed_files()
        return pdf_filename in processed_files

    def read_prompt_file(self, prompt_path):
        """读取prompt文件内容"""
        try:
            with open(prompt_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            print(f"读取prompt文件失败: {e}")
            return None

    def call_deepseek_api(self, prompt, content):
        """调用DeepSeek API"""
        try:
            if len(content) > 100000:
                content = content[:100000] + "\n\n[内容已截断...]"

            full_prompt = f"{prompt}\n\n[文献内容]\n{content}"

            data = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 4000
            }

            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=data,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                print(f"API调用失败: {response.status_code}, {response.text}")
                return None

        except Exception as e:
            print(f"API调用异常: {e}")
            return None

    def save_result(self, result, filename, pdf_name=None):
        """保存结果到results文件夹"""
        try:
            results_dir = "results"
            if not os.path.exists(results_dir):
                os.makedirs(results_dir)

            if pdf_name:
                pdf_folder = os.path.splitext(pdf_name)[0]
                pdf_results_dir = os.path.join(results_dir, pdf_folder)
                if not os.path.exists(pdf_results_dir):
                    os.makedirs(pdf_results_dir)
                filepath = os.path.join(pdf_results_dir, filename)
            else:
                filepath = os.path.join(results_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as file:
                if isinstance(result, dict):
                    json.dump(result, file, ensure_ascii=False, indent=2)
                else:
                    file.write(str(result))

            return True
        except Exception as e:
            print(f"保存结果失败: {e}")
            return False

    def process_entry_with_prompts(self, entry, screening_criteria=None):
        """使用 Prompt 处理单个文献条目 (优先使用 XML 内容，PDF 可选)"""
        title = entry.get('title', 'Unknown Title')
        print(f"开始处理文献: {title[:50]}...")
        
        # 构建分析内容：优先使用 Title + Abstract
        content_to_analyze = f"Title: {title}\n"
        if entry.get('abstract'):
            content_to_analyze += f"Abstract: {entry.get('abstract')}\n"
        
        # 处理 Prompt
        prompt_files = ["prompts/prompt1.txt"]
        if not os.path.exists("prompts"):
            print("错误：prompts文件夹不存在！")
            return False

        results = {}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 仅处理 Prompt 1
        prompt_file = prompt_files[0]
        if not os.path.exists(prompt_file):
            print(f"  警告：prompt文件不存在: {prompt_file}")
            return False

        prompt_content = self.read_prompt_file(prompt_file)
        if not prompt_content:
            return False
        
        # 注入筛选标准
        if screening_criteria:
            if "{screening_criteria}" in prompt_content:
                prompt_content = prompt_content.replace("{screening_criteria}", screening_criteria)
            else:
                prompt_content += f"\n\n补充筛选标准：\n{screening_criteria}"

        api_result = self.call_deepseek_api(prompt_content, content_to_analyze)
        if api_result:
            try:
                # 尝试解析 AI 返回的 JSON
                # 假设 AI 返回的是一个 JSON 列表 [{"exclusion_reason": "...", ...}]
                # 有时候 AI 可能会在 JSON 外面加 ```json ... ```，需要清理
                cleaned_result = api_result.strip()
                if cleaned_result.startswith('```json'):
                    cleaned_result = cleaned_result[7:]
                if cleaned_result.endswith('```'):
                    cleaned_result = cleaned_result[:-3]
                
                parsed_json = json.loads(cleaned_result)
                if isinstance(parsed_json, list) and len(parsed_json) > 0:
                    ai_decision = parsed_json[0]
                else:
                    ai_decision = parsed_json if isinstance(parsed_json, dict) else {}
                
                # 合并 XML 原文信息与 AI 筛选结论
                final_record = {
                    "title": entry.get('title'),
                    "extracted_abstract": entry.get('abstract'),
                    "authors": entry.get('authors'),
                    "journal": entry.get('journal'),
                    "year": entry.get('year'),
                    "doi": entry.get('doi'),
                    "source_xml": entry.get('source_xml'),
                    
                    # AI 决策部分
                    "exclusion_reason": ai_decision.get("exclusion_reason", ""),
                    "number_exclusion_reason": ai_decision.get("number_exclusion_reason", ""),
                    "include_or_not": ai_decision.get("include_or_not", "no"), # 默认 no 以防万一
                    
                    "processing_time": timestamp,
                    "raw_ai_response": api_result # 保留原始响应以备查
                }
                
                results["screening_result"] = final_record
                
                # 保存最终结果
                safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '-', '_')]).strip()[:50]
                self.save_result(final_record, f"screening_result_{timestamp}.json", safe_title)
                return True
                
            except json.JSONDecodeError:
                print(f"  AI 返回的 JSON 解析失败: {api_result[:100]}...")
                # 仍然保存原始结果，标记为解析失败
                self.save_result({"raw": api_result, "error": "JSON Parse Error"}, f"error_result_{timestamp}.txt", safe_title)
                return False
        else:
            print(f"  Prompt 1 API调用失败")
            return False

    def process_single_entry_with_retry(self, entry, max_retries=2, screening_criteria=None):
        """处理单个条目，带重试机制"""
        title = entry.get('title', 'Unknown')
        total_attempts = max_retries + 1

        for attempt in range(1, total_attempts + 1):
            try:
                success = self.process_entry_with_prompts(entry, screening_criteria)
                if success:
                    return {"title": title, "success": True, "error": None}
                else:
                    raise RuntimeError("函数返回失败")

            except Exception as e:
                error_msg = str(e)
                self.safe_print(f"✗ {title[:30]}... 第 {attempt} 次失败: {error_msg}")
                if attempt < total_attempts:
                    time.sleep(2)
                else:
                    return {"title": title, "success": False, "error": error_msg}

    def load_xml_references(self, datasets_dir):
        """
        从 datasets 目录加载 XML 引用文件。
        现在它会查找目录下所有的 .xml 文件，每个文件可能只包含一篇文献。
        """
        entries = []
        xml_files = [f for f in os.listdir(datasets_dir) if f.lower().endswith('.xml')]
        
        # 过滤掉汇总的大文件，避免重复处理
        # 假设汇总文件通常叫 references.xml 或 references_deduplicated_*.xml
        # 而拆分后的文件通常以标题命名，或者我们可以在 split 步骤加个前缀？
        # 暂时简单处理：如果文件名包含 "references" 且有其他不包含的文件，则优先处理其他文件
        
        single_entry_files = [f for f in xml_files if not f.startswith('references')]
        if not single_entry_files:
             single_entry_files = xml_files # Fallback
        
        print(f"找到 {len(single_entry_files)} 个单篇文献 XML 文件")

        for xml_file in single_entry_files:
            try:
                tree = ET.parse(os.path.join(datasets_dir, xml_file))
                root = tree.getroot()
                # 兼容单篇和多篇 XML 结构
                refs = root.findall('Reference')
                for ref in refs:
                    entry = {
                        'title': ref.find('Title').text if ref.find('Title') is not None else '',
                        'abstract': ref.find('Abstract').text if ref.find('Abstract') is not None else '',
                        'authors': [a.text for a in ref.findall('Authors/Author') if a.text],
                        'journal': ref.find('Journal').text if ref.find('Journal') is not None else '',
                        'year': ref.find('Year').text if ref.find('Year') is not None else '',
                        'doi': ref.find('DOI').text if ref.find('DOI') is not None else '',
                        'source_xml': xml_file # 记录来源文件，方便后续追踪
                    }
                    entries.append(entry)
            except Exception as e:
                print(f"解析 XML {xml_file} 失败: {e}")
        
        return entries

    def process_all_pdfs_in_datasets(self, force_reprocess=False, screening_criteria=None):
        """批量处理 datasets 中的 XML 文献条目"""
        datasets_dir = "datasets"
        if not os.path.exists(datasets_dir):
            print(f"数据集文件夹不存在: {datasets_dir}")
            return 0, []

        # 1. 加载 XML 条目
        entries = self.load_xml_references(datasets_dir)
        if not entries:
            print("未找到任何文献条目 (XML)")
            return 0, []

        print(f"从 XML 中加载了 {len(entries)} 条文献")
        
        # 2. 过滤已处理条目 (简单基于 Title 去重/检查状态)
        entries_to_process = []
        results_dir = "results"
        
        for entry in entries:
            title = entry.get('title', '')
            safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '-', '_')]).strip()[:50]
            
            # 检查 results/safe_title 目录是否存在且有 complete_analysis
            entry_dir = os.path.join(results_dir, safe_title)
            if not force_reprocess and os.path.exists(entry_dir) and any(f.startswith('complete_analysis') for f in os.listdir(entry_dir)):
                continue
            
            entries_to_process.append(entry)

        if not entries_to_process:
            print("所有文献均已处理")
            return 0, []

        print(f"开始处理 {len(entries_to_process)} 条新文献...")
        
        # 3. 多线程处理
        results = []
        total_count = len(entries_to_process)
        processed_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_entry = {
                executor.submit(self.process_single_entry_with_retry, entry, max_retries=2, screening_criteria=screening_criteria): entry
                for entry in entries_to_process
            }

            for future in as_completed(future_to_entry):
                result = future.result()
                results.append(result)
                processed_count += 1
                self.safe_print(f"[PROGRESS] {processed_count}/{total_count}")

        # 4. 统计
        success_count = sum(1 for r in results if r["success"])
        failed_files = [r["title"] for r in results if not r["success"]]

        self.safe_print(f"\n批量处理完成! 成功: {success_count}, 失败: {len(failed_files)}")
        return success_count, failed_files

class Processor(PDFProcessor):
    pass 
