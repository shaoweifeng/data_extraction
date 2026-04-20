from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Project, Document, ExtractionTask, Stage, StageData
from .serializers import ProjectSerializer, DocumentSerializer, ExtractionTaskSerializer, StageSerializer, StageDataSerializer
from .tasks import run_extraction_pipeline
import os
import shutil
from django.conf import settings
from celery import current_app
from django.utils import timezone
import json
from django.db import models
from django.contrib.auth.models import User

class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    def perform_create(self, serializer):
        if self.request.user and self.request.user.is_authenticated:
            creator = self.request.user
        else:
            creator, _ = User.objects.get_or_create(username='root', defaults={'email': ''})
        project = serializer.save(creator=creator)
        # 创建项目时自动初始化六个阶段
        for stage_type, _ in Stage.STAGE_TYPES:
            Stage.objects.create(project=project, stage_type=stage_type)

    @action(detail=True, methods=['get'])
    def stages(self, request, pk=None):
        project = self.get_object()
        stages = project.stages.all()
        return Response(StageSerializer(stages, many=True).data)

    @action(detail=True, methods=['post'])
    def upload_stage_data(self, request, pk=None):
        project = self.get_object()
        print(f"[DEBUG] upload_stage_data called for project {project.id}")
        
        stage_type = request.data.get('stage_type')
        if not stage_type:
            print("[DEBUG] stage_type missing")
            return Response({"error": "stage_type is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            stage = project.stages.get(stage_type=stage_type)
        except Stage.DoesNotExist:
            print(f"[DEBUG] Stage {stage_type} not found")
            return Response({"error": "Stage not found"}, status=status.HTTP_404_NOT_FOUND)

        files = request.FILES.getlist('files')
        print(f"[DEBUG] Received {len(files)} files")
        
        data_type = request.data.get('data_type', 'INPUT')
        uploaded_data = []
        try:
            for f in files:
                print(f"[DEBUG] Processing file: {f.name}")
                stage_data = StageData.objects.create(
                    stage=stage,
                    file=f,
                    filename=f.name,
                    data_type=data_type,
                    source='UPLOAD'
                )
                uploaded_data.append(StageDataSerializer(stage_data).data)
        except Exception as e:
            print(f"[DEBUG] Error saving file: {e}")
            import traceback
            traceback.print_exc()
            return Response({"error": f"File save failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(uploaded_data, status=status.HTTP_201_CREATED)

    # 兼容旧 API
    @action(detail=True, methods=['post'])
    def upload_documents(self, request, pk=None):
        project = self.get_object()
        files = request.FILES.getlist('files')
        uploaded_docs = []
        for f in files:
            doc = Document.objects.create(
                project=project,
                file=f,
                filename=f.name
            )
            uploaded_docs.append(DocumentSerializer(doc).data)
        return Response(uploaded_docs, status=status.HTTP_201_CREATED)

    # 删除某条 StageData（项目级别的文件项）
    # DELETE /api/projects/{id}/stage_data/{data_id}/
    @action(detail=True, methods=['delete'], url_path='stage_data/(?P<data_id>[^/.]+)')
    def delete_stage_data(self, request, pk=None, data_id=None):
        project = self.get_object()
        try:
            sd = StageData.objects.get(pk=data_id)
        except StageData.DoesNotExist:
            return Response({"error": "StageData not found"}, status=status.HTTP_404_NOT_FOUND)
        if sd.stage.project_id != project.id:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        sd.file.delete(save=False)
        sd.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def start_extraction(self, request, pk=None):
        project = self.get_object()
        force = request.data.get('force', False)
        
        # 【修复】启动前清理可能残留的 STOP 文件，防止任务立即停止
        workspace_dir = os.path.join(settings.BASE_DIR, "workspaces", f"project_{project.id}")
        stop_file = os.path.join(workspace_dir, "screening_ai", "STOP")
        if os.path.exists(stop_file):
            os.remove(stop_file)
            print(f"[DEBUG] 已清理残留的 STOP 文件: {stop_file}")
        
        # 获取筛选标准 (从 SCREEN_1 阶段的 metadata 中获取，如果前端没传，就去数据库查)
        screening_criteria = request.data.get('screening_criteria')
        if not screening_criteria:
            try:
                stage = project.stages.get(stage_type='SCREEN_1')
                screening_criteria = stage.metadata.get('screening_criteria')
            except Stage.DoesNotExist:
                pass
                
        # 触发 Celery 任务
        task = run_extraction_pipeline.delay(project.id, force, screening_criteria)
        return Response({"task_id": task.id, "message": "任务已启动"}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'])
    def screening_progress_files(self, request, pk=None):
        project = self.get_object()

        candidate_tasks = ExtractionTask.objects.filter(
            project=project,
            status__in=['PROCESSING', 'STOPPED', 'COMPLETED']
        ).order_by('-created_at')[:1]

        # 【修复】workspace 路径简化为 workspaces/project_{id}/
        workspace_dir = os.path.join(settings.BASE_DIR, "workspaces", f"project_{project.id}")
        target_results_dir = os.path.join(workspace_dir, "screening_ai", "results")
        
        if not os.path.exists(target_results_dir):
            return Response({"task_id": None, "processed": []})

        selected_task_id = candidate_tasks[0].id if candidate_tasks else None

        processed_map = {}
        for root_dir, _, files in os.walk(target_results_dir):
            for file_name in files:
                if not file_name.lower().endswith('.json'):
                    continue
                file_path = os.path.join(root_dir, file_name)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    continue

                source_xml = data.get('source_xml')
                if not source_xml:
                    continue

                try:
                    mtime = os.path.getmtime(file_path)
                except Exception:
                    mtime = 0

                existing = processed_map.get(source_xml)
                if existing and existing.get('_mtime', 0) >= mtime:
                    continue

                processed_map[source_xml] = {
                    "source_xml": source_xml,
                    "title": data.get('title') or '',
                    "include_or_not": data.get('include_or_not') or '',
                    "exclusion_reason": data.get('exclusion_reason') or '',
                    "number_exclusion_reason": data.get('number_exclusion_reason') or '',
                    "_mtime": mtime,
                }

        processed_list = list(processed_map.values())
        processed_list.sort(key=lambda x: (x.get('_mtime', 0), x.get('source_xml', '')), reverse=True)
        for item in processed_list:
            item.pop('_mtime', None)

        return Response({"task_id": selected_task_id, "processed": processed_list})

    @action(detail=True, methods=['post'])
    def stop_extraction(self, request, pk=None):
        project = self.get_object()
        tasks = project.tasks.filter(status='PROCESSING').exclude(celery_task_id__isnull=True).exclude(celery_task_id='')
        if not tasks.exists():
            return Response({"message": "No running task"}, status=status.HTTP_200_OK)

        stopped = 0
        for t in tasks:
            t.status = 'STOPPED'
            t.completed_at = timezone.now()
            current_logs = t.logs or ""
            suffix = "\n[STOPPED] 用户手动停止任务"
            t.logs = (current_logs + suffix) if suffix.strip() not in current_logs else current_logs
            t.save()

            # 【修复】workspace 路径简化为 workspaces/project_{id}/
            workspace_dir = os.path.join(settings.BASE_DIR, "workspaces", f"project_{project.id}")
            stop_path = os.path.join(workspace_dir, "screening_ai", "STOP")
            try:
                os.makedirs(os.path.dirname(stop_path), exist_ok=True)
                with open(stop_path, "w", encoding="utf-8") as f:
                    f.write("STOP")
            except Exception:
                pass
            
            try:
                current_app.control.revoke(t.celery_task_id, terminate=True, signal='SIGTERM')
            except Exception:
                pass
            stopped += 1

        return Response({"message": "Stopped", "stopped_tasks": stopped}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def generate_report(self, request, pk=None):
        """
        Step 5: 生成 Excel/RIS 报表
        """
        import sys
        import subprocess
        from django.utils import timezone
        from django.core.files.base import ContentFile

        project = self.get_object()
        
        # 获取 SCREEN_1 阶段
        try:
            screen1_stage = Stage.objects.get(project=project, stage_type='SCREEN_1')
        except Stage.DoesNotExist:
            return Response({"error": "Stage SCREEN_1 not found"}, status=status.HTTP_404_NOT_FOUND)
            
        # 【修复】workspace 路径简化为 workspaces/project_{id}/
        workspace_dir = os.path.join(settings.BASE_DIR, "workspaces", f"project_{project.id}")
        target_results_dir = os.path.join(workspace_dir, "screening_ai", "results")
        
        if not os.path.exists(target_results_dir):
            return Response({"error": "No screening results found. Please run AI screening first."}, status=status.HTTP_404_NOT_FOUND)
        
        # 检查是否有 JSON 结果
        has_json = False
        for root_dir, _, files in os.walk(target_results_dir):
            if any(f.lower().endswith('.json') for f in files):
                has_json = True
                break
        
        if not has_json:
            return Response({"error": "No JSON results found in screening results directory"}, status=status.HTTP_404_NOT_FOUND)

        # 清理旧的 OUTPUT 文件 (Excel/RIS)
        StageData.objects.filter(stage=screen1_stage, data_type='OUTPUT', description__in=['AI初筛结果 (Excel)', 'AI初筛结果 (EndNote/RIS)']).delete()
        
        # 调用 aggregator.py
        aggregator_script = os.path.join(settings.BASE_DIR, "structural_screening", "03_result_aggregation", "aggregator.py")
        output_dir = os.path.join(workspace_dir, "report_output")  # 生成到 workspace 下的子目录
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            r = subprocess.run(
                [
                    sys.executable, 
                    aggregator_script,
                    "--input_dir", target_results_dir,
                    "--output_dir", output_dir
                ],
                cwd=workspace_dir,
                text=True,
                capture_output=True
            )
            
            if r.returncode != 0:
                return Response({"error": f"Aggregation failed: {r.stderr}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
            # 保存结果到 StageData
            generated_files = []
            
            # Excel
            excel_path = os.path.join(output_dir, "AI初筛结果.xlsx")
            if os.path.exists(excel_path):
                with open(excel_path, 'rb') as f:
                    filename = f"{project.name}_AI初筛结果_{timezone.now().strftime('%Y%m%d%H%M%S')}.xlsx"
                    # 直接保存到项目目录下，不要再拼接相对路径，File Field 会自动处理 upload_to
                    # 但我们需要控制具体路径到 projects/project_X/SCREEN_1/
                    # upload_to 在 model 中定义，这里我们可以手动指定 name 为相对路径
                    
                    # 修正：之前代码使用了 os.path.join(f"projects/project_{project.id}/SCREEN_1", filename)
                    # 如果 model 的 upload_to 是 'stage_files/%Y/%m/%d/'，那么 Django 会拼接这两者
                    # 导致路径变成 media/stage_files/.../projects/...
                    # 检查 StageData model 定义：
                    # file = models.FileField(upload_to='stage_files/%Y/%m/%d/')
                    
                    # 如果我们想保存到特定目录，应该修改 model 或者在这里做一些 hack
                    # 为了简单起见，我们先让 Django 管理文件，但文件名带上项目名
                    # 如果用户坚持要特定目录结构，我们需要自定义 upload_to 或者 storage
                    
                    # 这里的需求是：去掉嵌套的三层
                    # 之前的代码：relative_path = os.path.join(f"projects/project_{project.id}/SCREEN_1", filename)
                    # 导致 media/projects/project_4/SCREEN_1/projects/project_4/SCREEN_1/filename
                    
                    # 修正：直接使用文件名，让 Django 决定存储位置（默认 upload_to）
                    # 或者，如果我们想强制路径，需要自定义 Storage。
                    # 但为了满足用户的“去掉嵌套”要求，我们只要不重复拼接路径即可。
                    
                    # 如果我们想保存到 media/projects/project_X/SCREEN_1/
                    # 我们需要手动移动文件到那里，然后把 file field 指向该路径（相对于 MEDIA_ROOT）
                    
                    final_dir = os.path.join(settings.MEDIA_ROOT, "projects", f"project_{project.id}", "SCREEN_1")
                    os.makedirs(final_dir, exist_ok=True)
                    final_path = os.path.join(final_dir, filename)
                    
                    # 复制文件到最终目录
                    import shutil
                    with open(excel_path, 'rb') as src, open(final_path, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                        
                    # 创建 StageData，手动指定 name 为相对 MEDIA_ROOT 的路径
                    relative_path = os.path.join("projects", f"project_{project.id}", "SCREEN_1", filename)
                    
                    sd = StageData.objects.create(
                        stage=screen1_stage,
                        # 这里不能直接传 ContentFile，否则会由 upload_to 处理
                        # 我们直接赋值 name 字符串？不行，FileField 需要文件对象
                        # 我们可以用 SimpleUploadedFile 或者手动赋值
                    )
                    sd.file.name = relative_path # 强制指定路径
                    sd.filename = filename
                    sd.data_type = 'OUTPUT'
                    sd.source = 'TOOL_GENERATED'
                    sd.description = 'AI初筛结果 (Excel)'
                    sd.save()
                    
                    generated_files.append({"id": sd.id, "filename": filename, "url": sd.file.url, "type": "excel"})

            # RIS (aggregator.py 需要支持生成 RIS，或者我们单独处理)
            # aggregator.py 里有 convert_to_ris 函数，但 main 函数里没调用？
            # 让我们在 views 里调用它
            sys.path.append(os.path.dirname(aggregator_script))
            import aggregator
            ris_path = os.path.join(output_dir, "AI初筛结果.ris")
            if aggregator.convert_to_ris(target_results_dir, ris_path):
                 with open(ris_path, 'rb') as f:
                    filename_ris = f"{project.name}_AI初筛结果_{timezone.now().strftime('%Y%m%d%H%M%S')}.ris"
                    
                    final_dir = os.path.join(settings.MEDIA_ROOT, "projects", f"project_{project.id}", "SCREEN_1")
                    os.makedirs(final_dir, exist_ok=True)
                    final_path_ris = os.path.join(final_dir, filename_ris)
                    
                    import shutil
                    with open(ris_path, 'rb') as src, open(final_path_ris, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    
                    relative_path_ris = os.path.join("projects", f"project_{project.id}", "SCREEN_1", filename_ris)
                    
                    sd_ris = StageData.objects.create(
                        stage=screen1_stage,
                    )
                    sd_ris.file.name = relative_path_ris
                    sd_ris.filename = filename_ris
                    sd_ris.data_type = 'OUTPUT'
                    sd_ris.source = 'TOOL_GENERATED'
                    sd_ris.description = 'AI初筛结果 (EndNote/RIS)'
                    sd_ris.save()
                    
                    generated_files.append({"id": sd_ris.id, "filename": filename_ris, "url": sd_ris.file.url, "type": "ris"})

            return Response({
                "message": "Report generated successfully", 
                "files": generated_files
            })

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, *args, **kwargs):
        project = self.get_object()
        processing_tasks = project.tasks.filter(status='PROCESSING').exclude(celery_task_id__isnull=True).exclude(celery_task_id='')
        for t in processing_tasks:
            try:
                current_app.control.revoke(t.celery_task_id, terminate=True, signal='SIGTERM')
            except Exception:
                pass
        workspace_base = os.path.join(settings.BASE_DIR, "workspaces")
        workspace_dir = os.path.join(workspace_base, f"project_{project.id}")
        workspace_base_real = os.path.realpath(workspace_base)
        workspace_dir_real = os.path.realpath(workspace_dir)
        if workspace_dir_real.startswith(workspace_base_real + os.sep) and os.path.exists(workspace_dir_real):
            shutil.rmtree(workspace_dir_real, ignore_errors=True)
        return super().destroy(request, *args, **kwargs)

class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

class ExtractionTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ExtractionTask.objects.all()
    serializer_class = ExtractionTaskSerializer

    @action(detail=False, methods=['get'])
    def latest_by_project(self, request):
        project_id = request.query_params.get('project_id')
        if not project_id:
            return Response({"error": "project_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        task = ExtractionTask.objects.filter(project_id=project_id).order_by('-created_at').first()
        if not task:
            return Response({"message": "No tasks found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(ExtractionTaskSerializer(task).data)
    
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """读取任务的日志文件（方案二：日志文件化）"""
        task = self.get_object()
        
        # 优先使用 log_file（新方案）
        if task.log_file and os.path.exists(task.log_file):
            try:
                with open(task.log_file, 'r', encoding='utf-8') as f:
                    log_content = f.read()
                return Response({"logs": log_content})
            except Exception as e:
                return Response({"error": f"Failed to read log file: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Fallback：使用旧的 logs 字段（向后兼容）
        if task.logs:
            return Response({"logs": task.logs})
        
        return Response({"logs": "暂无日志"})
    
    @action(detail=True, methods=['get'])
    def logs_stream(self, request, pk=None):
        """流式读取日志文件的最后 N 行（用于实时监控）"""
        from django.http import StreamingHttpResponse
        
        task = self.get_object()
        lines = int(request.query_params.get('lines', 100))  # 默认返回最后 100 行
        
        if not task.log_file or not os.path.exists(task.log_file):
            return Response({"logs": task.logs or "暂无日志"})
        
        try:
            # 读取文件的最后 N 行
            with open(task.log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                tail_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                log_content = ''.join(tail_lines)
            
            return Response({"logs": log_content})
        except Exception as e:
            return Response({"error": f"Failed to read log file: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Stage.objects.all()
    serializer_class = StageSerializer

    @action(detail=True, methods=['patch'])
    def update_metadata(self, request, pk=None):
        stage = self.get_object()
        metadata = request.data.get('metadata')
        if not metadata:
            return Response({"error": "metadata is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # 使用 update 可能会覆盖掉其他 metadata 字段，改为直接修改字典并保存
        if stage.metadata is None:
            stage.metadata = {}
        stage.metadata.update(metadata)
        stage.save()

        # 额外逻辑：如果更新的是 screening_criteria，同步保存到文件系统 criteria.txt
        if 'screening_criteria' in metadata:
            criteria_content = metadata['screening_criteria']
            
            try:
                # 同时也作为 StageData 保存记录（可选，方便前端下载查看）
                # 检查是否已存在
                existing_criteria = StageData.objects.filter(stage=stage, filename='criteria.txt').first()
                if existing_criteria:
                    existing_criteria.file.delete(save=False)
                    existing_criteria.delete()

                from django.core.files.base import ContentFile
                StageData.objects.create(
                    stage=stage,
                    file=ContentFile(criteria_content.encode('utf-8'), name='criteria.txt'),
                    filename='criteria.txt',
                    data_type='INPUT',
                    source='USER_UPLOAD',
                    description='纳排标准文件'
                )

            except Exception as e:
                print(f"Error saving criteria file: {e}")

        return Response(StageSerializer(stage).data)

    @action(detail=True, methods=['post'])
    def process_references(self, request, pk=None):
        stage = self.get_object()
        if stage.stage_type != 'SCREEN_1':
             return Response({"error": "Only SCREEN_1 stage supports reference processing"}, status=status.HTTP_400_BAD_REQUEST)
        
        # 1. 获取该阶段所有 INPUT 的 Reference 文件
        input_files = stage.data.filter(data_type='INPUT')
        ref_files = [f for f in input_files if f.filename.lower().endswith(('.ris', '.bib', '.nbib', '.xml', '.ciw'))]
        
        if not ref_files:
            return Response({"error": "No reference files found"}, status=status.HTTP_400_BAD_REQUEST)
            
        old_outputs = stage.data.filter(
            data_type='OUTPUT'
        ).filter(
            models.Q(source='TOOL_GENERATED') |
            models.Q(filename__startswith='split_xmls/') |
            models.Q(filename__icontains='dedup_report') |
            models.Q(filename__icontains='references_deduplicated') |
            models.Q(description__in=['单篇文献 XML', '去重后的 XML 文献索引 (汇总)', '去重报告 (JSON)'])
        )
        for old_data in old_outputs:
            try:
                # 显式删除物理文件，以防万一
                if old_data.file and os.path.exists(old_data.file.path):
                    old_data.file.delete(save=False)
            except Exception as e:
                print(f"Error deleting file {old_data.filename}: {e}")
            old_data.delete()
            
        # 3. 调用 parse_refs 逻辑
        try:
            # 动态导入 structural_screening/01_reference_parsing/parser.py
            import sys
            import importlib.util
            from django.core.files.base import ContentFile
            
            parser_path = os.path.join(settings.BASE_DIR, 'structural_screening', '01_reference_parsing', 'parser.py')
            spec = importlib.util.spec_from_file_location("parser", parser_path)
            parser = importlib.util.module_from_spec(spec)
            sys.modules["parser"] = parser
            spec.loader.exec_module(parser)
            
            # 创建临时目录处理文件
            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                input_xml_names = set()
                # 将文件复制到临时目录
                for f in ref_files:
                    src = f.file.path
                    dst = os.path.join(temp_dir, f.filename)
                    shutil.copy(src, dst)
                    input_xml_names.add(os.path.basename(f.filename))
                    
                # 运行处理逻辑
                output_xml_path = os.path.join(temp_dir, 'references.xml')
                final_entries, report = parser.process_directory(temp_dir, output_xml_path, return_report=True)
                
                # parser.process_directory 内部已经调用了 split_xml_to_single_files
                # 生成的小 XML 文件现在都在 temp_dir 下
                
                # 读取生成的 XML 并保存到 StageData (OUTPUT)
                if os.path.exists(output_xml_path):
                    # 保存汇总的大 XML
                    with open(output_xml_path, 'rb') as f:
                        filename = f"references_deduplicated_{stage.project.id}.xml"
                        StageData.objects.create(
                            stage=stage,
                            file=ContentFile(f.read(), name=filename),
                            filename=filename,
                            data_type='OUTPUT',
                            source='TOOL_GENERATED',
                            description='去重后的 XML 文献索引 (汇总)'
                        )

                    report_filename = f"dedup_report_{stage.project.id}.json"
                    StageData.objects.create(
                        stage=stage,
                        file=ContentFile(json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8'), name=report_filename),
                        filename=report_filename,
                        data_type='OUTPUT',
                        source='TOOL_GENERATED',
                        description='去重报告 (JSON)'
                    )
                    
                    # 创建 split_xmls 子目录（实际上 StageData 默认是平铺在 upload_to 指定的目录，如果要分目录需要自定义 upload_to 或手动移动）
                    # 简单起见，我们还是用 StageData，但文件名可以带前缀，或者我们接受平铺
                    # 既然用户想要放到内部文件夹，我们可以手动指定 upload_to 的效果，但这需要修改 Model 或者 override save
                    # 比较简单的做法是：在文件名中体现目录结构？不，Django FileField 会处理
                    # 更好的做法：StageData 模型保存后，文件其实是在 media/projects/project_X/SCREEN_1/ 下
                    # 我们可以通过修改 filename 参数来试图创建子目录，Django Storage 通常支持
                    
                    split_dir_name = "split_xmls"
                    
                    # 保存拆分后的小 XML 文件
                    # 遍历 temp_dir 下的所有 .xml 文件，除了 references.xml
                    for f_name in os.listdir(temp_dir):
                        if f_name.endswith('.xml') and f_name != 'references.xml':
                            if f_name in input_xml_names:
                                continue
                            f_path = os.path.join(temp_dir, f_name)
                            with open(f_path, 'rb') as f:
                                # 尝试在 filename 中包含路径
                                relative_path = os.path.join(split_dir_name, f_name)
                                StageData.objects.create(
                                    stage=stage,
                                    file=ContentFile(f.read(), name=relative_path), # 这里的 name 决定了保存路径
                                    filename=relative_path, # 数据库里显示的文件名也带上路径，方便前端筛选
                                    data_type='OUTPUT',
                                    source='TOOL_GENERATED',
                                    description='单篇文献 XML'
                                )
                        
                    # 更新 Metadata
                    stage.metadata.update({
                        'total_refs': len(final_entries), # 实际上去重后的数量
                        'deduplicated_count': report.get('duplicates_removed'),
                        'duplicate_groups': report.get('duplicate_groups'),
                        'total_entries_found': report.get('total_entries_found'),
                    })
                    stage.save()
                    
                    return Response({
                        "message": "Reference processing completed",
                        "total_entries": len(final_entries),
                        "dedup_report": report
                    })
                else:
                    return Response({"error": "Failed to generate XML"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StageDataViewSet(viewsets.ModelViewSet):
    queryset = StageData.objects.all()
    serializer_class = StageDataSerializer
