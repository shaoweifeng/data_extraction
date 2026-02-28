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

class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    def perform_create(self, serializer):
        project = serializer.save()
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

    @action(detail=True, methods=['post'])
    def start_extraction(self, request, pk=None):
        project = self.get_object()
        force = request.data.get('force', False)
        
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

class StageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Stage.objects.all()
    serializer_class = StageSerializer

    @action(detail=True, methods=['patch'])
    def update_metadata(self, request, pk=None):
        stage = self.get_object()
        metadata = request.data.get('metadata')
        if not metadata:
            return Response({"error": "metadata is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        stage.metadata.update(metadata)
        stage.save()
        return Response(StageSerializer(stage).data)

    @action(detail=True, methods=['post'])
    def process_references(self, request, pk=None):
        stage = self.get_object()
        if stage.stage_type != 'SCREEN_1':
             return Response({"error": "Only SCREEN_1 stage supports reference processing"}, status=status.HTTP_400_BAD_REQUEST)
        
        # 1. 获取该阶段所有 INPUT 的 Reference 文件 (.ris, .bib, .nbib)
        input_files = stage.data.filter(data_type='INPUT')
        ref_files = [f for f in input_files if f.filename.lower().endswith(('.ris', '.bib', '.nbib'))]
        
        if not ref_files:
            return Response({"error": "No reference files found"}, status=status.HTTP_400_BAD_REQUEST)
            
        # 2. 清理之前的 OUTPUT 结果
        # 删除所有 source='TOOL_GENERATED' 且 data_type='OUTPUT' 的 StageData
        old_outputs = stage.data.filter(data_type='OUTPUT', source='TOOL_GENERATED')
        for old_data in old_outputs:
            # 物理文件删除由 post_delete 信号处理
            old_data.delete()
            
        # 3. 调用 parse_refs 逻辑
        try:
            # 动态导入 reference_parsing/parser.py
            import sys
            import importlib.util
            from django.core.files.base import ContentFile
            
            parser_path = os.path.join(settings.BASE_DIR, 'reference_parsing', 'parser.py')
            spec = importlib.util.spec_from_file_location("parser", parser_path)
            parser = importlib.util.module_from_spec(spec)
            sys.modules["parser"] = parser
            spec.loader.exec_module(parser)
            
            # 创建临时目录处理文件
            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                # 将文件复制到临时目录
                for f in ref_files:
                    src = f.file.path
                    dst = os.path.join(temp_dir, f.filename)
                    shutil.copy(src, dst)
                    
                # 运行处理逻辑
                output_xml_path = os.path.join(temp_dir, 'references.xml')
                final_entries = parser.process_directory(temp_dir, output_xml_path)
                
                # 读取生成的 XML 并保存到 StageData (OUTPUT)
                if os.path.exists(output_xml_path):
                    with open(output_xml_path, 'rb') as f:
                        filename = f"references_deduplicated_{stage.project.id}.xml"
                        StageData.objects.create(
                            stage=stage,
                            file=ContentFile(f.read(), name=filename),
                            filename=filename,
                            data_type='OUTPUT',
                            source='TOOL_GENERATED',
                            description='去重后的 XML 文献索引'
                        )
                        
                    # 更新 Metadata
                    stage.metadata.update({
                        'total_refs': len(final_entries), # 实际上去重后的数量
                        'deduplicated_count': 'See logs' # 这里简单处理
                    })
                    stage.save()
                    
                    return Response({
                        "message": "Reference processing completed",
                        "total_entries": len(final_entries)
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
