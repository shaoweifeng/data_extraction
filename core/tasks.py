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
def run_reference_parsing_pipeline(self, project_id, file_ids=None):
    """步骤 1: 文献解析任务 - 将 .ris/.bib/.nbib 等格式解析成 XML"""
    # 创建任务记录
    task_obj = Task.objects.create(
        project_id=project_id,
        task_type='reference_parsing',
        celery_task_id=self.request.id,
        status='running',
        config={'file_ids': file_ids} if file_ids else {}
    )
    
    project = Project.objects.get(id=project_id)
    
    logs = []
    def add_log(msg):
        logs.append(msg)
        task_obj.logs = "\n".join(logs)
        task_obj.save()
    
    add_log(f"[启动] 开始文献解析任务 (项目: {project.name})")
    
    try:
        # 获取 SCREEN_1 阶段的 parse 步骤
        screen1_stage = ProjectStage.objects.get(project=project, stage_key='SCREEN_1')
        parse_step = StageStep.objects.get(stage=screen1_stage, step_key='parse')
        
        parse_step.status = 'in_progress'
        parse_step.started_at = timezone.now()
        parse_step.save()
        
        # 获取待解析的文件
        if file_ids:
            input_files = DataFile.objects.filter(id__in=file_ids, project=project)
        else:
            input_files = DataFile.objects.filter(
                project=project,
                step=parse_step,
                data_category='input'
            )
        
        add_log(f"[准备] 找到 {input_files.count()} 个输入文件")
        
        # 准备工作区
        base_dir = settings.BASE_DIR
        workspace_root = os.path.join(base_dir, "workspaces", f"project_{project_id}")
        workspace_dir = os.path.join(
            workspace_root,
            f"task_{task_obj.id}_{timezone.now().strftime('%Y%m%d%H%M%S')}",
        )
        input_dir = os.path.join(workspace_dir, "input")
        output_dir = os.path.join(workspace_dir, "output")
        split_dir = os.path.join(workspace_dir, "split_xmls")
        
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(split_dir, exist_ok=True)
        
        # 复制输入文件到工作区
        for df in input_files:
            dest_path = os.path.join(input_dir, df.filename)
            shutil.copy(df.file.path, dest_path)
            add_log(f"[复制] {df.filename}")
        
        # 调用解析脚本
        parser_script = os.path.join(base_dir, "structural_screening", "01_reference_parsing", "parser.py")
        
        import importlib.util
        spec = importlib.util.spec_from_file_location("parser", parser_script)
        parser = importlib.util.module_from_spec(spec)
        sys.modules["parser"] = parser
        spec.loader.exec_module(parser)
        
        # 解析并生成统一 XML
        merged_xml_path = os.path.join(output_dir, "references.xml")
        result = parser.process_directory(input_dir, merged_xml_path, return_report=True)
        
        # process_directory 返回 (final_entries, report) 当 return_report=True
        if isinstance(result, tuple):
            final_entries, report = result
        else:
            final_entries = result
            report = {'total_entries': len(final_entries)}
        
        add_log(f"[解析] 成功解析 {report.get('total_entries_found', report.get('total_entries', 0))} 条文献")
        add_log(f"[去重] 去重后保留 {report.get('final_unique_entries', len(final_entries))} 条文献")
        
        # 保存合并的 XML 文件
        with open(merged_xml_path, 'rb') as f:
            from django.core.files import File
            django_file = File(f)
            DataFile.objects.create(
                project=project,
                stage=screen1_stage,
                step=parse_step,
                filename="references.xml",
                file=django_file,
                data_category='output',
                source='tool_generated',
                description='合并后的文献 XML'
            )
        add_log(f"[保存] 合并 XML: references.xml")
        
        # 拆分成单个 XML 文件
        add_log(f"[拆分] 开始拆分为单篇文献...")
        all_entries = parser.parse_xml(merged_xml_path)
        parser.split_xml_to_single_files(all_entries, split_dir)
        
        # 保存拆分后的 XML 文件到数据库
        split_count = 0
        for filename in os.listdir(split_dir):
            if filename.endswith('.xml'):
                filepath = os.path.join(split_dir, filename)
                with open(filepath, 'rb') as f:
                    from django.core.files import File
                    django_file = File(f)
                    DataFile.objects.create(
                        project=project,
                        stage=screen1_stage,
                        step=parse_step,
                        filename=filename,
                        file=django_file,
                        data_category='intermediate',
                        source='tool_generated',
                        description='单篇文献 XML'
                    )
                split_count += 1
        
        add_log(f"[保存] 拆分 XML: {split_count} 个文件")
        
        parse_step.status = 'completed'
        parse_step.completed_at = timezone.now()
        parse_step.save()
        
        task_obj.status = 'completed'
        task_obj.completed_at = timezone.now()
        add_log("[完成] 文献解析任务成功")
        
    except Exception as e:
        parse_step.status = 'failed'
        parse_step.save()
        
        task_obj.status = 'failed'
        task_obj.error_message = str(e)
        add_log(f"[错误] {str(e)}")
        import traceback
        add_log(traceback.format_exc())
    
    task_obj.save()
    return task_obj.status == 'completed'


@shared_task(bind=True)
def run_deduplication_pipeline(self, project_id):
    """步骤 2: 自动去重任务 - 基于标题去重"""
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
        # 获取 SCREEN_1 阶段
        screen1_stage = ProjectStage.objects.get(project=project, stage_key='SCREEN_1')
        parse_step = StageStep.objects.get(stage=screen1_stage, step_key='parse')
        
        # 获取或创建去重步骤
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
        dedup_step.status = 'in_progress'
        dedup_step.started_at = timezone.now()
        dedup_step.save()
        
        # 获取拆分后的单篇 XML 文件
        split_files = DataFile.objects.filter(
            project=project,
            step=parse_step,
            data_category='intermediate',
            description='单篇文献 XML'
        )
        
        add_log(f"[准备] 找到 {split_files.count()} 个待去重文件")
        
        if split_files.count() == 0:
            raise ValueError("没有找到待去重的文献文件，请先执行文献解析")
        
        # 准备工作区
        base_dir = settings.BASE_DIR
        workspace_dir = os.path.join(
            base_dir, "workspaces", f"project_{project_id}",
            f"task_{task_obj.id}_{timezone.now().strftime('%Y%m%d%H%M%S')}"
        )
        input_dir = os.path.join(workspace_dir, "input_xmls")
        output_dir = os.path.join(workspace_dir, "dedup_xmls")
        
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        # 复制文件到工作区
        for df in split_files:
            shutil.copy(df.file.path, os.path.join(input_dir, df.filename))
        
        # 简单去重逻辑：基于 Title 标签去重
        import xml.etree.ElementTree as ET
        seen_titles = set()
        duplicates = []
        kept_files = []
        
        add_log(f"[去重] 开始基于标题去重...")
        
        for filename in os.listdir(input_dir):
            if not filename.endswith('.xml'):
                continue
                
            filepath = os.path.join(input_dir, filename)
            try:
                tree = ET.parse(filepath)
                root = tree.getroot()
                
                # 提取标题
                title_elem = root.find('.//Title')
                if title_elem is not None and title_elem.text:
                    title = title_elem.text.strip().lower()
                    
                    if title in seen_titles:
                        duplicates.append(filename)
                        add_log(f"[重复] {filename}")
                    else:
                        seen_titles.add(title)
                        kept_files.append(filename)
                        # 复制到输出目录
                        shutil.copy(filepath, os.path.join(output_dir, filename))
                else:
                    # 没有标题的也保留
                    kept_files.append(filename)
                    shutil.copy(filepath, os.path.join(output_dir, filename))
            except Exception as e:
                add_log(f"[警告] 解析 {filename} 失败: {str(e)}")
                # 解析失败的也保留
                kept_files.append(filename)
                shutil.copy(filepath, os.path.join(output_dir, filename))
        
        add_log(f"[统计] 原始文献: {split_files.count()} 篇")
        add_log(f"[统计] 去重后保留: {len(kept_files)} 篇")
        add_log(f"[统计] 重复文献: {len(duplicates)} 篇")
        
        # 保存去重后的文件到数据库
        for filename in kept_files:
            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'rb') as f:
                from django.core.files import File
                django_file = File(f)
                DataFile.objects.create(
                    project=project,
                    stage=screen1_stage,
                    step=dedup_step,
                    filename=filename,
                    file=django_file,
                    data_category='intermediate',
                    source='tool_generated',
                    description='去重后的文献 XML'
                )
        
        add_log(f"[保存] 已保存 {len(kept_files)} 个去重后的文件到数据库")
        
        # 更新步骤元数据
        dedup_step.metadata = {
            'total_files': split_files.count(),
            'kept_files': len(kept_files),
            'duplicates': len(duplicates),
            'duplicate_rate': f"{len(duplicates) / split_files.count() * 100:.2f}%"
        }
        dedup_step.status = 'completed'
        dedup_step.completed_at = timezone.now()
        dedup_step.save()
        
        task_obj.status = 'completed'
        task_obj.completed_at = timezone.now()
        add_log("[完成] 去重任务成功")
        
    except Exception as e:
        dedup_step.status = 'failed'
        dedup_step.save()
        
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
        
        # 获取 SCREEN_1 阶段
        screen1_stage = ProjectStage.objects.get(project=project, stage_key='SCREEN_1')
        
        # 优先获取去重后的 XML，否则获取解析后的 XML
        # 1. 先尝试去重步骤的输出
        dedup_step_exists = StageStep.objects.filter(stage=screen1_stage, step_key='dedup').exists()
        
        if dedup_step_exists:
            dedup_step = StageStep.objects.get(stage=screen1_stage, step_key='dedup')
            dedup_files = DataFile.objects.filter(
                project=project,
                step=dedup_step,
                data_category='intermediate',
                description='去重后的文献 XML'
            )
            
            if dedup_files.exists():
                for df in dedup_files:
                    shutil.copy(df.file.path, os.path.join(datasets_dir, df.filename))
                add_log(f"[数据] 使用去重后的文件: {dedup_files.count()} 个")
            else:
                # 2. 如果去重步骤没有输出，使用解析步骤的拆分 XML
                parse_step = StageStep.objects.get(stage=screen1_stage, step_key='parse')
                split_files = DataFile.objects.filter(
                    project=project,
                    step=parse_step,
                    data_category='intermediate',
                    description='单篇文献 XML'
                )
                for df in split_files:
                    shutil.copy(df.file.path, os.path.join(datasets_dir, df.filename))
                add_log(f"[数据] 使用解析后的拆分文件: {split_files.count()} 个")
        else:
            # 3. 如果没有去重步骤，直接使用解析步骤的拆分 XML
            parse_step = StageStep.objects.get(stage=screen1_stage, step_key='parse')
            split_files = DataFile.objects.filter(
                project=project,
                step=parse_step,
                data_category='intermediate',
                description='单篇文献 XML'
            )
            
            if not split_files.exists():
                raise ValueError("没有找到待筛选的文献文件，请先执行文献解析")
            
            for df in split_files:
                shutil.copy(df.file.path, os.path.join(datasets_dir, df.filename))
            add_log(f"[数据] 使用解析后的拆分文件: {split_files.count()} 个")
        
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
                'can_skip': False,
                'status': 'in_progress'
            }
        )
        export_step.status = 'in_progress'
        export_step.started_at = timezone.now()
        export_step.save()
        
        # 获取 AI 初筛步骤的结果文件
        ai_step = StageStep.objects.get(stage=screen1_stage, step_key='ai_screen')
        result_files = DataFile.objects.filter(
            project=project,
            step=ai_step,
            data_category='output'
        )
        
        add_log(f"[准备] 找到 {result_files.count()} 个AI初筛结果文件")
        
        if result_files.count() == 0:
            raise ValueError("没有找到AI初筛结果文件，请先执行AI初筛")
        
        # 准备工作区
        base_dir = settings.BASE_DIR
        workspace_dir = os.path.join(
            base_dir, "workspaces", f"project_{project_id}",
            f"report_{timezone.now().strftime('%Y%m%d%H%M%S')}"
        )
        input_dir = os.path.join(workspace_dir, "screening_results")
        output_dir = os.path.join(workspace_dir, "reports")
        
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        # 复制AI初筛结果到工作区
        for df in result_files:
            shutil.copy(df.file.path, os.path.join(input_dir, df.filename))
        
        # 调用聚合脚本
        aggregator_script = os.path.join(base_dir, "structural_screening", "03_result_aggregation", "aggregator.py")
        
        import importlib.util
        spec = importlib.util.spec_from_file_location("aggregator", aggregator_script)
        aggregator = importlib.util.module_from_spec(spec)
        sys.modules["aggregator"] = aggregator
        spec.loader.exec_module(aggregator)
        
        # 执行聚合
        add_log(f"[聚合] 开始聚合AI初筛结果...")
        aggregator.main(input_dir, output_dir)
        
        # 保存生成的报告文件到数据库
        report_count = 0
        for filename in os.listdir(output_dir):
            if filename.endswith(('.xlsx', '.ris', '.txt')):
                filepath = os.path.join(output_dir, filename)
                with open(filepath, 'rb') as f:
                    from django.core.files import File
                    django_file = File(f)
                    DataFile.objects.create(
                        project=project,
                        stage=screen1_stage,
                        step=export_step,
                        filename=filename,
                        file=django_file,
                        data_category='output',
                        source='tool_generated',
                        description='AI初筛结果报告'
                    )
                add_log(f"[保存] {filename}")
                report_count += 1
        
        add_log(f"[完成] 生成 {report_count} 个报告文件")
        
        export_step.status = 'completed'
        export_step.completed_at = timezone.now()
        export_step.save()
        
        task_obj.status = 'completed'
        task_obj.completed_at = timezone.now()
        add_log("[完成] 结果报表生成成功")
        
    except Exception as e:
        export_step.status = 'failed'
        export_step.save()
        
        task_obj.status = 'failed'
        task_obj.error_message = str(e)
        add_log(f"[错误] {str(e)}")
        import traceback
        add_log(traceback.format_exc())
    
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
