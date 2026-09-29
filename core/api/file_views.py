import json
from pathlib import Path

from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse
from django.db.models import F, Q
from rest_framework import serializers as drf_serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import ActivityLog, DataFile, ProjectStage, StageStep
from ..artifacts.types import ArtifactType
from ..serializers import DataFileSerializer
from ..services.access_policy import ProjectAccessPolicy
from core.screening.services.import_validation import FORMAT_BY_EXTENSION


class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = DataFile.objects.filter(
            project__in=ProjectAccessPolicy.visible_projects(self.request.user)
        )

        qp = self.request.query_params
        project_id = qp.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)

        stage_id = qp.get('stage')
        if stage_id:
            qs = qs.filter(stage_id=stage_id)

        step_id = qp.get('step')
        if step_id:
            qs = qs.filter(step_id=step_id)

        data_category = qp.get('data_category')
        if data_category:
            qs = qs.filter(data_category=data_category)
        if data_category == 'input':
            qs = qs.filter(
                Q(reference_import_file__isnull=True)
                | Q(reference_import_file__removed_revision__isnull=True)
                | Q(
                    reference_import_file__removed_revision__gt=
                    F('reference_import_file__import_batch__corpus__revision')
                )
            )

        return qs.select_related('stage', 'step', 'created_by').prefetch_related('versions')

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        total = qs.count()
        qp = request.query_params
        try:
            limit = int(qp.get('limit', 200))
            offset = int(qp.get('offset', 0))
        except (TypeError, ValueError):
            limit = 200
            offset = 0
        qs = qs[offset : offset + limit]
        serializer = self.get_serializer(qs, many=True)
        return Response({'total': total, 'results': serializer.data})

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """通过受权限保护的附件响应下载原始文件。

        文件始终以二进制流返回，不对 TXT 进行解码或重新编码。
        """
        from .common import check_permission

        if not check_permission(request.user, 'file.download'):
            raise PermissionDenied("缺少权限：file.download")

        data_file = self.get_object()
        private_file = None
        try:
            private_file = data_file.reference_import_file.raw_file
        except (AttributeError, ObjectDoesNotExist):
            pass
        downloadable = private_file or data_file.file
        if not downloadable:
            return Response({'error': '文件不存在'}, status=status.HTTP_404_NOT_FOUND)

        downloadable.open('rb')
        return FileResponse(
            downloadable,
            as_attachment=True,
            filename=data_file.filename,
            content_type='application/octet-stream',
        )

    @action(detail=True, methods=['get'], url_path='parse-report')
    def parse_report(self, request, pk=None):
        """Return the latest full parse diagnostics for one uploaded index file."""
        source_file = self.get_object()
        report_file = (
            DataFile.objects.filter(
                project=source_file.project,
                data_category='output',
                metadata__artifact_type=ArtifactType.SCREENING_PARSE_REPORT_JSON,
                metadata__source_file_id=source_file.id,
            )
            .order_by('-created_at')
            .first()
        )
        if report_file is None or not report_file.file:
            return Response({'error': '尚无解析报告'}, status=status.HTTP_404_NOT_FOUND)

        try:
            report_file.file.open('rb')
            return Response(json.load(report_file.file))
        except (OSError, ValueError, TypeError):
            return Response({'error': '解析报告不可读取'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            try:
                report_file.file.close()
            except Exception:
                pass

    def perform_create(self, serializer):
        user = self.request.user
        from .common import check_permission
        if not check_permission(user, 'file.upload'):
            raise PermissionDenied("缺少权限：file.upload")

        uploaded_file = self.request.FILES.get('file')
        requested_category = serializer.validated_data.get('data_category', 'input')
        if (
            requested_category == 'input'
            and uploaded_file
            and Path(uploaded_file.name).suffix.lower() in FORMAT_BY_EXTENSION
        ):
            raise drf_serializers.ValidationError({
                'error': {
                    'code': 'screening_import_endpoint_required',
                    'message': '文献索引请使用 /api/screening-imports/ 批次上传接口。',
                }
            })
        if uploaded_file and not serializer.validated_data.get('filename'):
            serializer.validated_data['filename'] = uploaded_file.name

        project = serializer.validated_data.get('project')
        if project:
            if not ProjectAccessPolicy.can_access_project(user, project):
                raise PermissionDenied("无权向该项目上传文件")

            stage = serializer.validated_data.get('stage')
            step = serializer.validated_data.get('step')
            if stage and stage.project_id != project.id:
                raise drf_serializers.ValidationError("stage 不属于指定项目")
            if step and step.stage.project_id != project.id:
                raise drf_serializers.ValidationError("step 不属于指定项目")
            if stage and step and step.stage_id != stage.id:
                raise drf_serializers.ValidationError("step 不属于指定 stage")

            project_id = project.id
            data_category = serializer.validated_data.get('data_category', 'input')

            if data_category == 'input' and not serializer.validated_data.get('stage'):
                try:
                    screen1_stage = ProjectStage.objects.get(project_id=project_id, stage_key='SCREEN_1')
                    serializer.validated_data['stage'] = screen1_stage
                    try:
                        parse_step = StageStep.objects.get(stage=screen1_stage, step_key='parse')
                        serializer.validated_data['step'] = parse_step
                    except StageStep.DoesNotExist:
                        pass
                except ProjectStage.DoesNotExist:
                    pass

        if uploaded_file and not serializer.validated_data.get('file_size'):
            serializer.validated_data['file_size'] = uploaded_file.size

        if uploaded_file and not serializer.validated_data.get('file_type'):
            import mimetypes

            file_type, _ = mimetypes.guess_type(uploaded_file.name)
            if file_type:
                serializer.validated_data['file_type'] = file_type

        _filename = uploaded_file.name if uploaded_file else serializer.validated_data.get('filename', '')
        _project = serializer.validated_data.get('project')

        serializer.save(created_by=user)

        if _project:
            ActivityLog.objects.create(
                project=_project,
                operation_type='file_add',
                operation_detail={'filename': _filename},
                created_by=user,
            )

    def perform_destroy(self, instance):
        from ..services import reset_downstream_on_input_delete

        if instance.data_category == 'input' and instance.project:
            reset_downstream_on_input_delete(instance, self.request.user)

        ActivityLog.objects.create(
            project=instance.project,
            operation_type='file_delete',
            operation_detail={'filename': instance.filename},
            created_by=self.request.user,
        )
        instance.delete()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            instance.reference_import_file
        except (AttributeError, ObjectDoesNotExist):
            return super().destroy(request, *args, **kwargs)

        from core.screening.services.import_service import remove_source_file
        from core.screening.services.import_errors import ScreeningImportError

        try:
            remove_source_file(instance, request.user)
        except ScreeningImportError as exc:
            return Response({'error': exc.as_dict()}, status=exc.http_status)
        return Response(status=status.HTTP_204_NO_CONTENT)
