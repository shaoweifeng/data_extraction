import os
import sys
import subprocess
import shutil
from celery import shared_task
from django.utils import timezone
from .models import ExtractionTask, Project, Document
from django.conf import settings

@shared_task(bind=True)
def run_extraction_pipeline(self, project_id, force_reprocess=False, screening_criteria=None):
    task_obj = ExtractionTask.objects.create(
        project_id=project_id,
        celery_task_id=self.request.id,
        status='PROCESSING'
    )
    
    project = Project.objects.get(id=project_id)
    base_dir = settings.BASE_DIR
    workspace_root = os.path.join(base_dir, "workspaces", f"project_{project_id}")
    workspace_dir = os.path.join(
        workspace_root,
        f"task_{task_obj.id}_{timezone.now().strftime('%Y%m%d%H%M%S')}",
    )
    os.makedirs(workspace_dir, exist_ok=True)
    
    logs = []
    def add_log(msg):
        logs.append(msg)
        task_obj.logs = "\n".join(logs)
        task_obj.save()

    add_log(f"工作区: {workspace_dir}")
    try:
        shutil.copytree(
            os.path.join(base_dir, "screening_ai"),
            os.path.join(workspace_dir, "screening_ai"),
            ignore=shutil.ignore_patterns("__pycache__", "datasets", "results", "*.pyc"),
            dirs_exist_ok=True,
        )
        shutil.copytree(
            os.path.join(base_dir, "result_aggregation"),
            os.path.join(workspace_dir, "result_aggregation"),
            ignore=shutil.ignore_patterns("__pycache__", "results", "*.pyc"),
            dirs_exist_ok=True,
        )
        os.makedirs(os.path.join(workspace_dir, "screening_ai", "datasets"), exist_ok=True)
        os.makedirs(os.path.join(workspace_dir, "screening_ai", "results"), exist_ok=True)
        os.makedirs(os.path.join(workspace_dir, "result_aggregation", "results"), exist_ok=True)
    except Exception as e:
        task_obj.status = 'FAILED'
        add_log(f"初始化工作区失败: {str(e)}")
        task_obj.save()
        return False

    # 准备数据集：将 Stage 中的 INPUT 文件拷贝到工作区
    datasets_dir = os.path.join(workspace_dir, "screening_ai", "datasets")
    try:
        # 获取 SCREEN_1 阶段的输入文件
        from .models import Stage
        screen1_stage = Stage.objects.get(project_id=project_id, stage_type='SCREEN_1')
        input_files = screen1_stage.data.filter(data_type='INPUT')
        
        # 兼容旧逻辑：如果 Stage 没数据，尝试从 Project.documents 拿（但这实际上是旧逻辑了）
        # 这里我们优先使用 Stage 数据
        if input_files.exists():
            for doc in input_files:
                src = doc.file.path
                dst = os.path.join(datasets_dir, doc.filename)
                shutil.copy(src, dst)
        else:
            # Fallback to old documents
            for doc in project.documents.all():
                src = doc.file.path
                dst = os.path.join(datasets_dir, doc.filename)
                shutil.copy(src, dst)
    except Exception as e:
        add_log(f"准备数据集失败: {e}")

    # 执行 Step 1: 分析 PDF
    add_log(f"开始执行 PDF 分析 (项目: {project.name})...")
    if screening_criteria:
        add_log(f"使用纳排标准: {screening_criteria[:50]}...")
        
    # 我们不再通过 subprocess 调用 1.py，而是直接导入并调用它的类/函数，
    # 这样可以更好地传递 screening_criteria 参数。
    # 为了避免路径问题，我们还是把 CWD 设为工作区。
    
    pipeline1_dir = os.path.join(workspace_dir, "screening_ai")
    sys.path.append(pipeline1_dir)
    original_cwd = os.getcwd()
    os.chdir(pipeline1_dir)
    
    try:
        # 动态导入 screening_ai/screener.py 中的 Processor 类
        import importlib.util
        spec = importlib.util.spec_from_file_location("screener", "screener.py")
        screener = importlib.util.module_from_spec(spec)
        sys.modules["screener"] = screener
        spec.loader.exec_module(screener)
        
        # 实例化 Processor
        processor = screener.Processor()
        
        # 重定向 stdout 以捕获日志
        from io import StringIO
        capture_io = StringIO()
        original_stdout = sys.stdout
        sys.stdout = capture_io
        
        # 调用处理函数
        # 注意：我们需要修改 1.py 让 process_all_pdfs_in_datasets 接受 screening_criteria
        # 我之前已经修改了 1.py
        success_count, failed_files = processor.process_all_pdfs_in_datasets(
            force_reprocess=force_reprocess,
            screening_criteria=screening_criteria
        )
        
        # 恢复 stdout 并获取日志
        sys.stdout = original_stdout
        captured_logs = capture_io.getvalue()
        for line in captured_logs.splitlines():
            add_log(line)
            
        if success_count == 0 and len(failed_files) > 0:
             task_obj.status = 'FAILED'
             add_log("Step 1 失败: 所有文件处理失败")
             os.chdir(original_cwd) # 恢复 CWD
             task_obj.save()
             return False

    except Exception as e:
        task_obj.status = 'FAILED'
        add_log(f"Step 1 异常: {str(e)}")
        import traceback
        add_log(traceback.format_exc())
        os.chdir(original_cwd) # 恢复 CWD
        task_obj.save()
        return False
    
    os.chdir(original_cwd) # 恢复 CWD

    # 执行 Step 2: 生成 Excel
    add_log("开始执行标准化和 Excel 生成...")
    try:
        # Step 2.1: 运行 standard.py
        add_log("运行标准化处理 (standard.py)...")
        # standard.py 还在 screening_ai 目录下吗？或者需要移动到 result_aggregation？
        # 假设 standard.py 原来在 2/standard.py，现在应该在 result_aggregation/standard.py
        r1 = subprocess.run(
            [sys.executable, os.path.join(workspace_dir, "result_aggregation", "standard.py")],
            cwd=workspace_dir,
            text=True,
            capture_output=True
        )
        if r1.stdout: logs.append(r1.stdout)
        if r1.stderr: logs.append(r1.stderr)
        
        if r1.returncode != 0:
            task_obj.status = 'FAILED'
            add_log(f"Step 2.1 失败: {r1.stderr}")
            task_obj.save()
            return False

        # Step 2.2: 运行 aggregator.py
        add_log("运行 Excel 生成 (aggregator.py)...")
        r2 = subprocess.run(
            [sys.executable, os.path.join(workspace_dir, "result_aggregation", "aggregator.py")],
            cwd=workspace_dir,
            text=True,
            capture_output=True
        )
        if r2.stdout: logs.append(r2.stdout)
        if r2.stderr: logs.append(r2.stderr)
        
        if r2.returncode != 0:
            task_obj.status = 'FAILED'
            add_log(f"Step 2.2 失败: {r2.stderr}")
            task_obj.save()
            return False
                
        # 保存结果文件
        # Excel
        final_excel_path = os.path.join(workspace_dir, "result_aggregation", "免疫文献提取结果_合并版.xlsx")
        if os.path.exists(final_excel_path):
            # 将结果也作为 StageData 保存到 SCREEN_1 阶段的输出
            from .models import Stage, StageData
            try:
                screen1_stage = Stage.objects.get(project_id=project_id, stage_type='SCREEN_1')
                with open(final_excel_path, 'rb') as f:
                    from django.core.files import File
                    filename = f"screening_result_{project_id}_{timezone.now().strftime('%Y%m%d%H%M%S')}.xlsx"
                    # 保存到 Task
                    task_obj.result_excel.save(filename, File(f), save=False)
                    # 保存到 StageData
                    f.seek(0)
                    StageData.objects.create(
                        stage=screen1_stage,
                        file=File(f, name=filename),
                        filename=filename,
                        data_type='OUTPUT',
                        source='TOOL_GENERATED',
                        description='AI初筛结果 (Excel)'
                    )
            except Exception as e:
                 add_log(f"保存 Excel 到 StageData 失败: {e}")

        else:
            add_log("警告：未找到生成的 Excel 文件")
            
        # EndNote (RIS)
        try:
            sys.path.append(os.path.join(workspace_dir, "result_aggregation"))
            import aggregator  # 动态导入工作区里的 aggregator 模块
            
            json_results_dir = os.path.join(workspace_dir, "screening_ai", "results")
            final_ris_path = os.path.join(workspace_dir, "result_aggregation", "screening_result.ris")
            
            if aggregator.convert_to_ris(json_results_dir, final_ris_path):
                add_log("生成 RIS 文件成功")
                screen1_stage = Stage.objects.get(project_id=project_id, stage_type='SCREEN_1')
                with open(final_ris_path, 'rb') as f:
                    from django.core.files import File
                    filename_ris = f"screening_result_{project_id}_{timezone.now().strftime('%Y%m%d%H%M%S')}.ris"
                    StageData.objects.create(
                        stage=screen1_stage,
                        file=File(f, name=filename_ris),
                        filename=filename_ris,
                        data_type='OUTPUT',
                        source='TOOL_GENERATED',
                        description='AI初筛结果 (EndNote/RIS)'
                    )
            else:
                add_log("生成 RIS 文件失败或无数据")
                
        except Exception as e:
            add_log(f"生成 RIS 过程异常: {e}")
        
        task_obj.status = 'COMPLETED'
        task_obj.completed_at = timezone.now()
        add_log("全流水线执行成功！")
        task_obj.save()
        return True
        
    except Exception as e:
        task_obj.status = 'FAILED'
        add_log(f"全流水线异常: {str(e)}")
        task_obj.save()
        return False
