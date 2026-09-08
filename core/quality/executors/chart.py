"""QA 图表异步生成 Handler。"""

import base64
from datetime import datetime

from core.artifacts.types import ArtifactType
from core.executors.step_handler import BaseStepHandler
from core.executors.registry import register
from core.models import ActivityLog
from core.quality.services.chart_service import generate_chart_payload


def _write_data_url(path, data_url):
    if not data_url or ',' not in data_url:
        return False
    path.write_bytes(base64.b64decode(data_url.split(',', 1)[1]))
    return True


@register('qa_chart')
class QualityChartHandler(BaseStepHandler):
    """通过统一 StepExecutor 生成并登记 QA 图表产物。"""

    execution_mode = 'async'

    def execute(self) -> bool:
        quality_method = self.config.get('quality_method', 'QUADAS2')
        payload = generate_chart_payload(
            self.project_obj,
            quality_method,
            ref_ids=self.config.get('ref_ids') or None,
            study_labels=self.config.get('study_labels') or {},
            orientation=self.config.get('orientation', 'horizontal'),
            lang=self.config.get('lang', 'zh'),
        )

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        files = {}
        for artifact_type, payload_key, prefix in (
            (ArtifactType.QA_TRAFFIC_LIGHT_PNG, 'traffic_light_image', 'qa_traffic_light'),
            (ArtifactType.QA_PROPORTION_PNG, 'proportion_image', 'qa_proportion'),
        ):
            output_path = self.workspace / f'{prefix}_{quality_method}_{timestamp}.png'
            if not _write_data_url(output_path, payload[payload_key]):
                continue
            data_file = self.save_output_file(
                output_path,
                output_path.name,
                'QA交通灯图' if artifact_type == ArtifactType.QA_TRAFFIC_LIGHT_PNG else 'QA比例图',
            )
            data_file.metadata = {
                'artifact_type': artifact_type,
                'quality_method': quality_method,
                'chart_id': payload['chart'].id,
            }
            data_file.save(update_fields=['metadata', 'updated_at'])
            files[artifact_type] = data_file

        traffic_file = files.get(ArtifactType.QA_TRAFFIC_LIGHT_PNG)
        if traffic_file:
            payload['chart'].image_file = traffic_file
            payload['chart'].save(update_fields=['image_file'])

        payload['traffic_light_image'] = (
            files[ArtifactType.QA_TRAFFIC_LIGHT_PNG].file.url
            if ArtifactType.QA_TRAFFIC_LIGHT_PNG in files else None
        )
        payload['proportion_image'] = (
            files[ArtifactType.QA_PROPORTION_PNG].file.url
            if ArtifactType.QA_PROPORTION_PNG in files else None
        )
        payload['image_url'] = payload['traffic_light_image']
        payload.pop('chart')
        self.task_obj.result = payload
        self.task_obj.save(update_fields=['result', 'updated_at'])

        ActivityLog.objects.create(
            project=self.project_obj,
            operation_type='qa_generate_chart',
            operation_detail={
                'quality_method': quality_method,
                'ref_count': len(payload['traffic_light']),
                'task_id': self.task_obj.id,
            },
            created_by=self.task_obj.created_by,
        )
        return bool(files)
