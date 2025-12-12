import os
import json
import pdfplumber
import requests
from datetime import datetime
from config import base_url, api_key, max_workers
import fitz  # PyMuPDF - 既能提取文字又能处理图片
from PIL import Image
import io
import base64
import os
import time
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

    def extract_text_with_pymupdf(self, pdf_path):
        """使用PyMuPDF提取PDF文本和图片内容"""
        try:
            print("使用PyMuPDF提取PDF内容...")
            doc = fitz.open(pdf_path)
            full_text = ""
            image_count = 0

            for page_num in range(len(doc)):
                page = doc[page_num]
                print(f"  处理第 {page_num + 1}/{len(doc)} 页...")

                # 1. 提取文本内容
                text = page.get_text()
                if text.strip():
                    full_text += f"\n--- 第 {page_num + 1} 页文本 ---\n{text}\n"

                # 2. 提取图片并转换为文字描述
                image_list = page.get_images()
                if image_list:
                    print(f"    发现 {len(image_list)} 张图片")
                    for img_index, img in enumerate(image_list):
                        try:
                            # 获取图片
                            xref = img[0]
                            base_image = doc.extract_image(xref)
                            image_bytes = base_image["image"]

                            # 将图片转换为base64用于描述
                            image_b64 = base64.b64encode(image_bytes).decode('utf-8')

                            # 这里可以调用图片描述API，或者简单标记
                            full_text += f"\n[图片 {image_count + 1} - 第{page_num + 1}页]\n"
                            full_text += f"图片格式: {base_image['ext']}, 尺寸: {base_image['width']}x{base_image['height']}\n"
                            full_text += f"图片内容: [此处为图片，包含重要信息]\n"

                            image_count += 1

                        except Exception as img_e:
                            print(f"    处理图片 {img_index + 1} 失败: {img_e}")
                            continue

                # 3. 提取矢量图形中的文本（如果有）
                try:
                    # 使用不同的文本提取方法获取更多内容
                    text_blocks = page.get_text("dict")
                    for block in text_blocks.get("blocks", []):
                        if "lines" in block:
                            for line in block["lines"]:
                                for span in line["spans"]:
                                    if span["text"].strip():
                                        full_text += span["text"] + " "
                except:
                    pass

            doc.close()
            print(f"✓ PyMuPDF提取完成: 共{len(full_text)}字符, {image_count}张图片")
            return full_text if full_text.strip() else None

        except Exception as e:
            print(f"❌ PyMuPDF提取失败: {e}")
            return None

    def extract_text_with_pdfplumber(self, pdf_path):
        """使用pdfplumber作为备选提取方法"""
        try:
            print("使用pdfplumber提取文本...")
            with pdfplumber.open(pdf_path) as pdf:
                text = ""
                for page_num, page in enumerate(pdf.pages, 1):
                    print(f"  提取第 {page_num}/{len(pdf.pages)} 页...")

                    # 提取文本
                    page_text = page.extract_text()
                    if page_text:
                        text += f"\n--- 第 {page_num} 页 ---\n{page_text}\n"

                    # 提取表格
                    tables = page.extract_tables()
                    if tables:
                        for table_num, table in enumerate(tables, 1):
                            if table:
                                text += f"\n[表格 {table_num} 内容]\n"
                                for row_num, row in enumerate(table, 1):
                                    row_text = " | ".join(
                                        [str(cell).strip() for cell in row if cell is not None and str(cell).strip()])
                                    if row_text:
                                        text += f"行{row_num}: {row_text}\n"
                                text += "\n"

                return text if text.strip() else None

        except Exception as e:
            print(f"pdfplumber提取失败: {e}")
            return None

    def extract_pdf_text_combined(self, pdf_path):
        """结合多种方法提取PDF文本"""
        try:
            print("开始综合提取PDF内容...")

            # 方法1: 优先使用PyMuPDF（支持文字和图片）
            print("方法1: 使用PyMuPDF提取...")
            pymupdf_text = self.extract_text_with_pymupdf(pdf_path)

            if pymupdf_text and len(pymupdf_text.strip()) > 100:
                print("✓ PyMuPDF提取成功，使用该结果")
                return pymupdf_text

            # 方法2: 使用pdfplumber作为备选
            print("方法2: 使用pdfplumber提取...")
            pdfplumber_text = self.extract_text_with_pdfplumber(pdf_path)

            if pdfplumber_text:
                print("✓ pdfplumber提取成功，使用该结果")
                return pdfplumber_text

            # 方法3: 简化版提取
            print("方法3: 简化版提取...")
            simple_text = self.extract_pdf_text_simple(pdf_path)
            if simple_text:
                print("✓ 简化版提取成功")
                return simple_text

            print("❌ 所有提取方法均失败")
            return None

        except Exception as e:
            print(f"综合提取失败: {e}")
            return self.extract_pdf_text_simple(pdf_path)

    def extract_pdf_text_simple(self, pdf_path):
        """简化版文本提取"""
        try:
            # 尝试使用PyMuPDF的简单提取
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                page_text = page.get_text()
                if page_text:
                    text += page_text + "\n"
            doc.close()
            return text if text.strip() else None
        except:
            # 回退到pdfplumber
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    text = ""
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    return text if text.strip() else None
            except Exception as e:
                print(f"简化版提取失败: {e}")
                return None

    def analyze_pdf_structure(self, pdf_path):
        """分析PDF结构，判断类型"""
        try:
            print("分析PDF结构...")
            doc = fitz.open(pdf_path)

            # 统计信息
            total_pages = len(doc)
            text_page_count = 0
            image_page_count = 0
            total_images = 0

            for page_num in range(total_pages):
                page = doc[page_num]

                # 检查是否有文本
                text = page.get_text().strip()
                if text:
                    text_page_count += 1

                # 检查图片数量
                images = page.get_images()
                if images:
                    image_page_count += 1
                    total_images += len(images)

            doc.close()

            # 判断PDF类型
            pdf_type = "未知"
            if text_page_count == total_pages and total_images == 0:
                pdf_type = "纯文本PDF"
            elif image_page_count == total_pages and text_page_count == 0:
                pdf_type = "扫描版PDF"
            elif text_page_count > 0 and image_page_count > 0:
                pdf_type = "混合PDF"
            elif total_images > text_page_count:
                pdf_type = "图片为主PDF"

            analysis_result = {
                "总页数": total_pages,
                "有文本的页数": text_page_count,
                "有图片的页数": image_page_count,
                "总图片数": total_images,
                "PDF类型": pdf_type
            }

            print(f"PDF分析结果: {analysis_result}")
            return analysis_result

        except Exception as e:
            print(f"PDF结构分析失败: {e}")
            return None

    def read_prompt_file(self, prompt_path):
        """读取prompt文件内容"""
        try:
            with open(prompt_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            print(f"读取prompt文件失败: {e}")
            return None

    def call_deepseek_api(self, prompt, pdf_content):
        """调用DeepSeek API"""
        try:
            if len(pdf_content) > 100000:
                print(f"文本过长({len(pdf_content)}字符)，进行截断...")
                pdf_content = pdf_content[:100000] + "\n\n[内容已截断...]"

            full_prompt = f"{prompt}\n\n[完整病例信息]\n{pdf_content}"

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

            print(f"结果已保存到: {filepath}")
            return True
        except Exception as e:
            print(f"保存结果失败: {e}")
            return False

    def process_pdf_with_prompts(self, pdf_path):
        """使用三个prompt处理PDF文件"""
        pdf_filename = os.path.basename(pdf_path)
        print(f"开始处理PDF文件: {pdf_filename}")

        # 分析PDF结构
        pdf_analysis = self.analyze_pdf_structure(pdf_path)

        # 提取PDF文本
        pdf_content = self.extract_pdf_text_combined(pdf_path)

        if not pdf_content:
            print(f"PDF文本提取失败，跳过文件: {pdf_filename}")
            return False

        print(f"PDF文本提取成功，共{len(pdf_content)}个字符")

        # 处理三个prompt文件
        prompt_files = [
            "prompts/prompt1.txt",
            "prompts/prompt2.txt",
            "prompts/prompt3.txt"
        ]

        if not os.path.exists("prompts"):
            print("错误：prompts文件夹不存在！")
            return False

        results = {}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i, prompt_file in enumerate(prompt_files, 1):
            print(f"  处理Prompt {i} ({prompt_file})...")

            if not os.path.exists(prompt_file):
                print(f"  警告：prompt文件不存在: {prompt_file}")
                continue

            prompt_content = self.read_prompt_file(prompt_file)
            if not prompt_content:
                print(f"  Prompt {i} 读取失败，跳过")
                continue

            api_result = self.call_deepseek_api(prompt_content, pdf_content)
            if api_result:
                results[f"prompt{i}_result"] = api_result
                print(f"  Prompt {i} 处理完成")

                result_filename = f"prompt{i}_result_{timestamp}.txt"
                self.save_result(api_result, result_filename, pdf_filename)
            else:
                print(f"  Prompt {i} API调用失败")

        # 保存汇总结果
        if results:
            summary = {
                "pdf_file": pdf_filename,
                "pdf_analysis": pdf_analysis,
                "processing_time": timestamp,
                "text_length": len(pdf_content),
                "results_count": len(results),
                "results": results
            }
            self.save_result(summary, f"complete_analysis_{timestamp}.json", pdf_filename)
            print(f"  {pdf_filename} 处理完成！共处理了{len(results)}个prompt")

            self.mark_file_as_processed(pdf_filename, timestamp)
            return True
        else:
            print(f"  {pdf_filename} 处理失败，没有获得任何结果")
            return False

    def process_single_pdf_with_retry(self, pdf_file, datasets_dir, max_retries=2):
        """
        处理单个 PDF 文件，最多重试 max_retries 次（即总共尝试 max_retries + 1 次）
        - 第一次失败 → 重试第1次
        - 再失败 → 重试第2次
        - 还失败 → 彻底放弃
        
        返回: {"file": str, "success": bool, "error": str or None}
        """
        pdf_path = os.path.join(datasets_dir, pdf_file)
        total_attempts = max_retries + 1  # 总共尝试次数（默认 3 次）

        for attempt in range(1, total_attempts + 1):
            try:
                self.safe_print(f"[{pdf_file}] 第 {attempt} 次尝试处理...")
                success = self.process_pdf_with_prompts(pdf_path)
                
                if success:
                    self.safe_print(f"✓ {pdf_file} 处理成功（第 {attempt} 次）")
                    return {"file": pdf_file, "success": True, "error": None}
                else:
                    # 函数返回 False，视为“逻辑失败”，触发重试
                    raise RuntimeError("函数返回失败")

            except Exception as e:
                error_msg = str(e)
                self.safe_print(f"✗ {pdf_file} 第 {attempt} 次失败: {error_msg}")
                
                # 如果还没到最大尝试次数，就等 2 秒后重试
                if attempt < total_attempts:
                    self.safe_print(f"  → 等待 2 秒后重试...")
                    time.sleep(2)
                else:
                    # 最后一次也失败了，记录错误
                    self.safe_print(f"  → 已达最大重试次数，放弃处理 {pdf_file}")
                    return {"file": pdf_file, "success": False, "error": error_msg}

    def process_all_pdfs_in_datasets(self, force_reprocess=False):
        """批量处理datasets文件夹中的所有PDF文件"""
        datasets_dir = "datasets"

        if not os.path.exists(datasets_dir):
            print(f"数据集文件夹不存在: {datasets_dir}")
            return

        pdf_files = [f for f in os.listdir(datasets_dir) if f.lower().endswith('.pdf')]

        if not pdf_files:
            print("datasets文件夹中没有找到PDF文件")
            return

        processed_files = self.load_processed_files()

        if force_reprocess:
            files_to_process = pdf_files
            print(f"强制重新处理模式：发现 {len(pdf_files)} 个PDF文件，将全部重新处理...")
        else:
            files_to_process = []
            skipped_files = []

            for pdf_file in pdf_files:
                if self.is_file_processed(pdf_file):
                    skipped_files.append(pdf_file)
                else:
                    files_to_process.append(pdf_file)

            print(f"发现 {len(pdf_files)} 个PDF文件")
            print(f"其中 {len(skipped_files)} 个文件已处理，{len(files_to_process)} 个文件需要处理")

            if skipped_files:
                print("已跳过的文件:")
                for skipped_file in skipped_files:
                    processed_time = processed_files.get(skipped_file, {}).get('processed_time', '未知')
                    print(f"  - {skipped_file} (处理时间: {processed_time})")

        if not files_to_process:
            print("没有需要处理的新文件！")
            return

        print(f"\n开始批量处理 {len(files_to_process)} 个文件...")
        print("=" * 60)

        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {
                executor.submit(self.process_single_pdf_with_retry, pdf_file, datasets_dir, max_retries=2): pdf_file
                for pdf_file in files_to_process
            }

            for future in as_completed(future_to_file):
                result = future.result()
                results.append(result)

        # 统计
        success_count = sum(1 for r in results if r["success"])
        failed_files = [r["file"] for r in results if not r["success"]]

        # 输出总结
        self.safe_print("\n" + "=" * 60)
        self.safe_print("批量处理完成！")
        self.safe_print(f"总文件数: {len(files_to_process)}")
        self.safe_print(f"成功处理: {success_count}")
        self.safe_print(f"处理失败: {len(failed_files)}")

        if failed_files:
            self.safe_print("\n⚠️ 以下文件经多次尝试后仍失败，请人工检查：")
            for f in failed_files:
                self.safe_print(f"  - {f}")

        return success_count, failed_files

    def show_processing_status(self):
        """显示处理状态"""
        datasets_dir = "datasets"

        if not os.path.exists(datasets_dir):
            print(f"数据集文件夹不存在: {datasets_dir}")
            return

        pdf_files = [f for f in os.listdir(datasets_dir) if f.lower().endswith('.pdf')]
        processed_files = self.load_processed_files()

        print("=" * 60)
        print("PDF文件处理状态")
        print("=" * 60)

        if not pdf_files:
            print("datasets文件夹中没有找到PDF文件")
            return

        processed_count = 0
        unprocessed_count = 0

        for pdf_file in pdf_files:
            if pdf_file in processed_files:
                processed_count += 1
                processed_time = processed_files[pdf_file].get('processed_time', '未知')
                status = processed_files[pdf_file].get('status', '未知')
                pdf_type = processed_files[pdf_file].get('pdf_analysis', {}).get('PDF类型', '未知')
                print(f"✓ {pdf_file} (已处理 - {processed_time} - 类型: {pdf_type})")
            else:
                unprocessed_count += 1
                print(f"○ {pdf_file} (未处理)")

        print("-" * 60)
        print(f"总计: {len(pdf_files)} 个文件")
        print(f"已处理: {processed_count} 个")
        print(f"未处理: {unprocessed_count} 个")
        print("=" * 60)

    def test_pdf_extraction(self, pdf_path):
        """测试PDF文本提取功能"""
        print("测试PDF文本提取功能...")
        print(f"文件: {pdf_path}")
        print("-" * 40)

        if not os.path.exists(pdf_path):
            print("文件不存在！")
            return

        # 分析PDF结构
        analysis = self.analyze_pdf_structure(pdf_path)

        # 测试各种提取方法
        methods = [
            ("PyMuPDF综合提取", self.extract_text_with_pymupdf),
            ("pdfplumber提取", self.extract_text_with_pdfplumber),
            ("简化版提取", self.extract_pdf_text_simple),
            ("组合提取", self.extract_pdf_text_combined)
        ]

        for method_name, method_func in methods:
            print(f"\n{method_name}结果:")
            try:
                text = method_func(pdf_path)
                if text:
                    print(f"成功提取，字符数: {len(text)}")
                    print("前500字符预览:")
                    print(text[:500] + "..." if len(text) > 500 else text)
                else:
                    print("提取失败或内容为空")
            except Exception as e:
                print(f"提取异常: {e}")

            print("-" * 30)


def main():
    """主函数"""
    processor = PDFProcessor()

    # 显示处理状态
    processor.show_processing_status()

    # 询问用户处理方式
    print("\n请选择处理方式:")
    print("1. 只处理新增的PDF文件 (推荐)")
    print("2. 强制重新处理所有PDF文件")
    print("3. 只查看状态，不进行处理")
    print("4. 测试PDF文本提取功能")

    try:
        choice = input("请输入选择 (1/2/3/4): ").strip()

        if choice == "1":
            print("\n开始增量处理...")
            processor.process_all_pdfs_in_datasets(force_reprocess=False)
        elif choice == "2":
            confirm = input("确定要重新处理所有文件吗？这将覆盖现有结果 (y/N): ").strip().lower()
            if confirm in ['y', 'yes']:
                print("\n开始强制重新处理...")
                processor.process_all_pdfs_in_datasets(force_reprocess=True)
            else:
                print("已取消操作")
        elif choice == "3":
            print("仅查看状态，未进行处理")
        elif choice == "4":
            pdf_file = input("请输入要测试的PDF文件路径: ").strip()
            processor.test_pdf_extraction(pdf_file)
        else:
            print("无效选择，默认进行增量处理...")
            processor.process_all_pdfs_in_datasets(force_reprocess=False)

    except KeyboardInterrupt:
        print("\n\n用户中断操作")
    except Exception as e:
        print(f"\n操作异常: {e}")


if __name__ == "__main__":
    # 切换到当前脚本所在目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # 检查必要的文件夹
    for folder in ["datasets", "prompts", "results"]:
        if not os.path.exists(folder):
            print(f"创建文件夹: {folder}")
            os.makedirs(folder, exist_ok=True)

    main()