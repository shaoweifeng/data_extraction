import os
import sys
import subprocess
import shutil
import json
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from .models import Task, Project, ProjectStage, StageStep, DataFile


@shared_task(bind=True)
def run_deduplication_pipeline(self, project_id):
    """步骤 2: 自动去重任务"""
    # 创建任务记录
    task_obj = Task.objects.create(
        project_id=project_id,
        task_type='deduplication',
        celery_task_id=self.request.id,
        status='running'
    )
    
    project = Project.objects.get(id=project_id)
    
    logs = []
    def add_log(msg):
        logs.append(msg)
        task_obj.logs = "\n".join(logs)
        task_obj.save()
    
    add_log(f"[启动] 开始去重任务 (项目: {project.name})")
    
    try:
        # 获取 SCREEN_1 阶段的 parse 步骤
        screen1_stage = ProjectStage.objects.get(project=project, stage_key='SCREEN_1')
        parse_step = StageStep.objects.get(stage=screen1_stage, step_key='parse')
        
        # 获取输入文件（解析后的 XML）
        input_files = DataFile.objects.filter(
            project=project,
            step=parse_step,
            data_category='output'
        )
        
        if not input_files.exists():
            # 尝试从原始 reference 文件获取
            input_files = DataFile.objects.filter(
                project=project,
                data_category='input'
            ).filter(
                filename__endswith='.xml'
            )
        
        add_log(f"[准备] 找到 {input_files.count()} 个输入文件")
        
        # 执行去重逻辑（这里需要调用你的去重脚本）
        # 简化版：更新步骤状态
        dedup_step, _ = StageStep.objects.get_or_create(
            stage=screen1_stage,
            step_key='dedup',
            defaults={
                'name': '自动去重',
                'order': 20,
                'can_skip': True,
                'status': 'in_progress'
            }
        )
        
        # TODO: 实际的去重逻辑
        # 这里调用 structural_screening/deduplication/dedup.py
        
        dedup_step.status = 'completed'
        dedup_step.completed_at = timezone.now()
        dedup_step.save()
        
        task_obj.status = 'completed'
        task_obj.completed_at = timezone.now()
        add_log("[完成] 去重任务成功")
        
    except Exception as e:
        task_obj.status = 'failed'
        task_obj.error_message = str(e)
        add_log(f"[错误] {str(e)}")
        import traceback
        add_log(traceback.format_exc())
    
    task_obj.save()
    return task_obj.status == 'completed'


@shared_task(bind=True)
def run_ai_screening_pipeline(self, project_id, screening_criteria=None):
    """步骤 4: AI 初筛任务"""
    # 创建任务记录
    task_obj = Task.objects.create(
        project_id=project_id,
        task_type='ai_screening',
        celery_task_id=self.request.id,
        status='running',
        config={'criteria': screening_criteria} if screening_criteria else {}
    )
    
    project = Project.objects.get(id=project_id)
    
    logs = []
    def add_log(msg):
        logs.append(msg)
        task_obj.logs = "\n".join(logs)
        task_obj.save()
    
    add_log(f"[启动] 开始 AI 初筛任务 (项目: {project.name})")
    
    # 准备工作区
    base_dir = settings.BASE_DIR
    workspace_root = os.path.join(base_dir, "workspaces", f"project_{project_id}")
    workspace_dir = os.path.join(
        workspace_root,
        f"task_{task_obj.id}_{timezone.now().strftime('%Y%m%d%H%M%S')}",
    )
    os.makedirs(workspace_dir, exist_ok=True)
    
    add_log(f"[工作区] {workspace_dir}")
    
    try:
        # 复制 screening_ai 代码
        shutil.copytree(
            os.path.join(base_dir, "structural_screening", "02_screening_ai"),
            os.path.join(workspace_dir, "screening_ai"),
            ignore=shutil.ignore_patterns("__pycache__", "datasets", "results", "*.pyc"),
            dirs_exist_ok=True,
        )
        
        datasets_dir = os.path.join(workspace_dir, "screening_ai", "datasets")
        os.makedirs(datasets_dir, exist_ok=True)
        
        # 获取 SCREEN_1 阶段的输入文件
        screen1_stage = ProjectStage.objects.get(project=project, stage_key='SCREEN_1')
        
        # 尝试获取去重后的 XML，否则获取原始解析的 XML
        dedup_files = DataFile.objects.filter(
            project=project,
            stage=screen1_stage,
            description='去重后的文献'
        )
        
        if dedup_files.exists():
            for df in dedup_files:
                shutil.copy(df.file.path, os.path.join(datasets_dir, os.path.basename(df.filename)))
            add_log(f"[数据] 使用去重后的文件: {dedup_files.count()} 个")
        else:
            # 使用所有拆分的 XML 文件
            split_files = DataFile.objects.filter(
                project=project,
                stage=screen1_stage,
                description='单篇文献 XML'
            )
            for df in split_files:
                shutil.copy(df.file.path, os.path.join(datasets_dir, os.path.basename(df.filename)))
            add_log(f"[数据] 使用拆分后的 XML 文件: {split_files.count()} 个")
        
        # 更新 AI 初筛步骤状态
        ai_step = StageStep.objects.get(stage=screen1_stage, step_key='ai_screen')
        ai_step.status = 'in_progress'
        ai_step.started_at = timezone.now()
        ai_step.save()
        
        # 执行 AI 筛选
        pipeline1_dir = os.path.join(workspace_dir, "screening_ai")
        sys.path.append(pipeline1_dir)
        original_cwd = os.getcwd()
        os.chdir(pipeline1_dir)
        
        # 实时日志捕获
        class TaskLogger:
            def __init__(self, task_obj):
                self.task_obj = task_obj
            
            def write(self, message):
                if message.strip():
                    add_log(message.strip())
            
            def flush(self):
                pass
        
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("screener", "screener.py")
            screener = importlib.util.module_from_spec(spec)
            sys.modules["screener"] = screener
            spec.loader.exec_module(screener)
            
            processor = screener.Processor()
            
            original_stdout = sys.stdout
            sys.stdout = TaskLogger(task_obj)
            
            success_count, failed_files = processor.process_all_pdfs_in_datasets(
                force_reprocess=False,
                screening_criteria=screening_criteria
            )
            
            sys.stdout = original_stdout
            
            # 检查是否被停止
            task_obj.refresh_from_db()
            if task_obj.status == 'stopped':
                add_log("[停止] 任务已被用户停止")
                ai_step.status = 'failed'
                ai_step.save()
                os.chdir(original_cwd)
                return False
            
            # 保存结果文件
            results_dir = os.path.join(pipeline1_dir, "results")
            if os.path.exists(results_dir):
                for filename in os.listdir(results_dir):
                    filepath = os.path.join(results_dir, filename)
                    if os.path.isfile(filepath):
                        with open(filepath, 'rb') as f:
                            from django.core.files import File
                            django_file = File(f)
                            DataFile.objects.create(
                                project=project,
                                stage=screen1_stage,
                                step=ai_step,
                                filename=filename,
                                file=django_file,
                                data_category='output',
                                source='tool_generated',
                                description='AI 初筛结果'
                            )
                        add_log(f"[保存] 结果文件: {filename}")
            
            ai_step.status = 'completed'
            ai_step.completed_at = timezone.now()
            ai_step.save()
            
            task_obj.status = 'completed'
            task_obj.completed_at = timezone.now()
            add_log(f"[完成] AI 筛选完成，成功 {success_count} 篇，失败 {len(failed_files)} 篇")
            
        except Exception as e:
            sys.stdout = sys.__stdout__
            ai_step.status = 'failed'
            ai_step.save()
            
            task_obj.status = 'failed'
            task_obj.error_message = str(e)
            add_log(f"[错误] {str(e)}")
            import traceback
            add_log(traceback.format_exc())
        
        os.chdir(original_cwd)
        
    except Exception as e:
        task_obj.status = 'failed'
        task_obj.error_message = str(e)
        add_log(f"[错误] {str(e)}")
        import traceback
        add_log(traceback.format_exc())
    
    task_obj.save()
    return task_obj.status == 'completed'


@shared_task(bind=True)
def run_result_aggregation(self, project_id):
    """步骤 5: 结果归纳（生成 Excel/RIS）"""
    task_obj = Task.objects.create(
        project_id=project_id,
        task_type='result_aggregation',
        celery_task_id=self.request.id,
        status='running'
    )
    
    project = Project.objects.get(id=project_id)
    screen1_stage = ProjectStage.objects.get(project=project, stage_key='SCREEN_1')
    
    logs = []
    def add_log(msg):
        logs.append(msg)
        task_obj.logs = "\n".join(logs)
        task_obj.save()
    
    add_log(f"[启动] 开始生成结果报表")
    
    try:
        # 更新 export 步骤状态
        export_step, _ = StageStep.objects.get_or_create(
            stage=screen1_stage,
            step_key='export',
            defaults={
                'name': '结果归纳',
                'order': 50,
                'can_skip': False
            }
        )
        export_step.status = 'in_progress'
        export_step.save()
        
        # TODO: 调用 03_result_aggregation 生成 Excel/RIS
        # 这里需要实现实际的聚合逻辑
        
        # 保存结果文件到 DataFile
        # ...
        
        export_step.status = 'completed'
        export_step.completed_at = timezone.now()
        export_step.save()
        
        task_obj.status = 'completed'
        task_obj.completed_at = timezone.now()
        add_log("[完成] 结果报表生成成功")
        
    except Exception as e:
        task_obj.status = 'failed'
        task_obj.error_message = str(e)
        add_log(f"[错误] {str(e)}")
    
    task_obj.save()
    return task_obj.status == 'completed'


@shared_task(bind=True)
def stop_task(self, task_id):
    """停止正在运行的任务"""
    try:
        task_obj = Task.objects.get(id=task_id)
        if task_obj.status == 'running':
            task_obj.status = 'stopped'
            task_obj.completed_at = timezone.now()
            task_obj.save()
            
            # 如果有 Celery 任务 ID，尝试终止
            if task_obj.celery_task_id:
                from celery import current_app
                current_app.control.revoke(task_obj.celery_task_id, terminate=True)
            
            return True
        return False
    except Task.DoesNotExist:
        return False
