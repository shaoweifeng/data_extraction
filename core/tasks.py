import os
import sys
import subprocess
import shutil
import time
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
    
    # 【修复】不再为每个任务创建独立目录，而是复用同一个 workspace 实现断点续传
    workspace_dir = workspace_root
    os.makedirs(workspace_dir, exist_ok=True)
    
    logs = []
    def add_log(msg):
        logs.append(msg)
        task_obj.logs = "\n".join(logs)
        task_obj.save()

    add_log(f"工作区: {workspace_dir}")
    try:
        # 确保脚本文件存在（首次或者脚本更新时）
        screening_ai_target = os.path.join(workspace_dir, "screening_ai")
        if not os.path.exists(screening_ai_target) or force_reprocess:
            shutil.copytree(
                os.path.join(base_dir, "structural_screening", "02_screening_ai"),
                screening_ai_target,
                ignore=shutil.ignore_patterns("__pycache__", "datasets", "results", "*.pyc"),
                dirs_exist_ok=True,
            )
        
        result_aggregation_target = os.path.join(workspace_dir, "result_aggregation")
        if not os.path.exists(result_aggregation_target) or force_reprocess:
            shutil.copytree(
                os.path.join(base_dir, "structural_screening", "03_result_aggregation"),
                result_aggregation_target,
                ignore=shutil.ignore_patterns("__pycache__", "results", "*.pyc"),
                dirs_exist_ok=True,
            )
        
        # 确保必要的目录存在
        os.makedirs(os.path.join(workspace_dir, "screening_ai", "datasets"), exist_ok=True)
        os.makedirs(os.path.join(workspace_dir, "screening_ai", "results"), exist_ok=True)
        os.makedirs(os.path.join(workspace_dir, "result_aggregation", "results"), exist_ok=True)
    except Exception as e:
        task_obj.status = 'FAILED'
        add_log(f"初始化工作区失败: {str(e)}")
        task_obj.save()
        return False

    # 准备数据集：将 Stage 中的 INPUT 文件和拆分后的 XML OUTPUT 文件拷贝到工作区
    datasets_dir = os.path.join(workspace_dir, "screening_ai", "datasets")
    try:
        # 获取 SCREEN_1 阶段的输入文件和生成的拆分 XML
        from .models import Stage
        from django.db.models import Q
        screen1_stage = Stage.objects.get(project_id=project_id, stage_type='SCREEN_1')
        stage_files = screen1_stage.data.filter(
            Q(data_type='INPUT') | 
            (Q(data_type='OUTPUT') & Q(description='单篇文献 XML'))
        )
        
        # 兼容旧逻辑：如果 Stage 没数据，尝试从 Project.documents 拿（但这实际上是旧逻辑了）
        # 这里我们优先使用 Stage 数据
        if stage_files.exists():
            for doc in stage_files:
                src = doc.file.path
                # 确保文件名不包含路径，只取 basename
                filename = os.path.basename(doc.filename)
                dst = os.path.join(datasets_dir, filename)
                shutil.copy(src, dst)
        else:
            # Fallback to old documents
            for doc in project.documents.all():
                src = doc.file.path
                filename = os.path.basename(doc.filename)
                dst = os.path.join(datasets_dir, filename)
                shutil.copy(src, dst)
    except Exception as e:
        add_log(f"准备数据集失败: {e}")

    # 执行 Step 1: 分析 PDF
    add_log(f"开始执行 XML 分析 (项目: {project.name})...")
    if screening_criteria:
        add_log(f"使用纳排标准: {screening_criteria[:50]}...")
        
    # 我们不再通过 subprocess 调用 1.py，而是直接导入并调用它的类/函数，
    # 这样可以更好地传递 screening_criteria 参数。
    # 为了避免路径问题，我们还是把 CWD 设为工作区。
    
    pipeline1_dir = os.path.join(workspace_dir, "screening_ai")
    sys.path.append(pipeline1_dir)
    original_cwd = os.getcwd()
    os.chdir(pipeline1_dir)
    
    # 为了避免 MySQL OOM，使用文件化日志（方案二）
    class TaskLogger:
        def __init__(self, task_obj, workspace_dir):
            self.task_obj = task_obj
            self.log_path = os.path.join(workspace_dir, f"task_{task_obj.id}.log")
            
            # 确保日志目录存在
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            
            # 打开日志文件
            self.log_file = open(self.log_path, 'a', encoding='utf-8', buffering=1)  # 行缓冲
            
            # 只在创建时写一次 DB，保存日志文件路径
            task_obj.log_file = self.log_path
            task_obj.save(update_fields=['log_file'])
        
        def write(self, message):
            if message and message.strip():
                self.log_file.write(message)
                if not message.endswith('\n'):
                    self.log_file.write('\n')
                self.log_file.flush()  # 实时写文件，不写 DB
        
        def flush(self):
            """确保所有内容写入磁盘"""
            if hasattr(self, 'log_file') and self.log_file:
                self.log_file.flush()
        
        def close(self):
            """关闭日志文件"""
            if hasattr(self, 'log_file') and self.log_file:
                self.log_file.close()

    try:
        # 动态导入 screening_ai/screener.py 中的 Processor 类
        import importlib.util
        spec = importlib.util.spec_from_file_location("screener", "screener.py")
        screener = importlib.util.module_from_spec(spec)
        sys.modules["screener"] = screener
        spec.loader.exec_module(screener)
        
        # 实例化 Processor
        processor = screener.Processor()
        
        # 替换 Processor 实例的 print 方法（如果它有的话，或者替换 safe_print）
        # 但 screener.py 里是用 safe_print -> print
        # 所以我们需要替换 sys.stdout
        
        original_stdout = sys.stdout
        logger = TaskLogger(task_obj, workspace_dir)
        sys.stdout = logger
        
        # 调用处理函数
        success_count, failed_files = processor.process_all_pdfs_in_datasets(
            force_reprocess=force_reprocess,
            screening_criteria=screening_criteria
        )
        
        # 确保日志写入磁盘并关闭文件
        logger.flush()
        logger.close()
        
        # 恢复 stdout
        sys.stdout = original_stdout

        task_obj.refresh_from_db()
        if task_obj.status == 'STOPPED' or os.path.exists(os.path.join(pipeline1_dir, "STOP")):
            task_obj.status = 'STOPPED'
            if not task_obj.completed_at:
                task_obj.completed_at = timezone.now()
            add_log("AI 初筛任务已停止。")
            os.chdir(original_cwd)
            task_obj.save()
            return False
            
        if success_count == 0 and len(failed_files) > 0:
             task_obj.status = 'FAILED'
             add_log("Step 1 失败: 所有文件处理失败")
             os.chdir(original_cwd) # 恢复 CWD
             task_obj.save()
             return False

    except Exception as e:
        # 确保日志文件被正确关闭
        if 'logger' in locals():
            logger.flush()
            logger.close()
        sys.stdout = sys.__stdout__ # 确保恢复 stdout
        task_obj.status = 'FAILED'
        add_log(f"Step 1 异常: {str(e)}")
        import traceback
        add_log(traceback.format_exc())
        os.chdir(original_cwd) # 恢复 CWD
        task_obj.save()
        return False
    
    os.chdir(original_cwd) # 恢复 CWD

    # 执行 Step 2: 生成 Excel (已移至单独的 API 触发)
    
    task_obj.refresh_from_db()
    if task_obj.status == 'STOPPED' or os.path.exists(os.path.join(pipeline1_dir, "STOP")):
        task_obj.status = 'STOPPED'
        if not task_obj.completed_at:
            task_obj.completed_at = timezone.now()
        add_log("AI 初筛任务已停止。")
        task_obj.save()
        return False

    task_obj.status = 'COMPLETED'
    task_obj.completed_at = timezone.now()
    add_log("AI 初筛任务完成！请在下一步生成 Excel 报表。")
    task_obj.save()
    return True
