"""QA API 的请求参数校验器。

暂时保持现有函数视图和响应结构，只把输入 schema 从视图逻辑中抽离。
"""

from rest_framework import serializers

from core.models import QAReference
from core.services.ai_models_config import get_model_config


METHOD_CHOICES = [value for value, _ in QAReference.METHOD_CHOICES]
EVAL_MODE_CHOICES = [value for value, _ in QAReference.EVAL_MODE_CHOICES]
FULLTEXT_STATUS_CHOICES = [value for value, _ in QAReference.FULLTEXT_STATUS_CHOICES]


class IdListField(serializers.ListField):
    child = serializers.IntegerField(min_value=1)


class QARefImportInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    source_stage = serializers.ChoiceField(
        choices=['SCREEN_1', 'SCREEN_2'], default='SCREEN_1'
    )
    ref_ids = IdListField(required=False, default=list)


class QARefUpdateInputSerializer(serializers.Serializer):
    quality_method = serializers.ChoiceField(choices=METHOD_CHOICES, allow_blank=True, required=False)
    eval_mode = serializers.ChoiceField(choices=EVAL_MODE_CHOICES, allow_blank=True, required=False)
    selected_models = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False
    )
    fulltext_status = serializers.ChoiceField(choices=FULLTEXT_STATUS_CHOICES, required=False)
    title = serializers.CharField(max_length=500, required=False)
    first_author = serializers.CharField(max_length=200, allow_blank=True, required=False)
    year = serializers.IntegerField(min_value=0, max_value=3000, allow_null=True, required=False)
    journal = serializers.CharField(max_length=300, allow_blank=True, required=False)
    fulltext_file_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError('至少需要提供一个可更新字段')
        return attrs


class QABatchMethodInputSerializer(serializers.Serializer):
    ref_ids = IdListField(allow_empty=False)
    quality_method = serializers.ChoiceField(choices=METHOD_CHOICES)


class QAEvalStartInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    ref_ids = IdListField(required=False, default=list)
    model_ids = serializers.ListField(
        child=serializers.CharField(max_length=100), allow_empty=False
    )
    # 旧前端会显式传 null；当前服务已根据 model_ids 推导评价模式，
    # 因此对该兼容字段同时接受缺省、空字符串和 null。
    eval_mode = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_model_ids(self, value):
        invalid = [model_id for model_id in value if get_model_config(model_id) is None]
        if invalid:
            raise serializers.ValidationError(f'未知模型: {", ".join(invalid)}')
        return list(dict.fromkeys(value))


class QASignalConfirmInputSerializer(serializers.Serializer):
    human_judgment = serializers.CharField(max_length=100, trim_whitespace=True)


class QASignalBatchConfirmInputSerializer(serializers.Serializer):
    qa_ref_id = serializers.IntegerField(min_value=1)
    confirm_mode = serializers.ChoiceField(
        choices=['adopt_preselected', 'adopt_ai', 'specific_keys'],
        default='adopt_preselected',
    )
    signal_keys = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, default=list
    )

    def validate(self, attrs):
        if attrs['confirm_mode'] == 'specific_keys' and not attrs['signal_keys']:
            raise serializers.ValidationError('specific_keys 模式必须提供 signal_keys')
        return attrs


class QAChartRequestSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    quality_method = serializers.ChoiceField(choices=METHOD_CHOICES, default='QUADAS2')
    ref_ids = IdListField(required=False, default=list)


class QAChartGenerateInputSerializer(QAChartRequestSerializer):
    study_labels = serializers.DictField(
        child=serializers.CharField(max_length=500, allow_blank=True),
        required=False,
        default=dict,
    )
    orientation = serializers.ChoiceField(
        choices=['horizontal', 'vertical'], default='horizontal'
    )
    lang = serializers.ChoiceField(choices=['zh', 'en'], default='zh')


class QAChartSettingsInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    quality_method = serializers.ChoiceField(choices=METHOD_CHOICES)
    study_labels = serializers.DictField(
        child=serializers.CharField(max_length=500, allow_blank=True)
    )


class QAExportInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    quality_method = serializers.ChoiceField(choices=METHOD_CHOICES, default='QUADAS2')
    include_unconfirmed = serializers.BooleanField(default=False)
