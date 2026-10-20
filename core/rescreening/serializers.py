"""文献复筛 API 入参校验器。"""

from rest_framework import serializers

from core.models import RescreenReference


class IdListField(serializers.ListField):
    child = serializers.IntegerField(min_value=1)


class RescreenImportInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    source_stage = serializers.ChoiceField(choices=['SCREEN_1'], default='SCREEN_1')
    ref_ids = IdListField(required=False, default=list)


class RescreenCriteriaInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    criteria_list = serializers.ListField(
        child=serializers.CharField(allow_blank=False, trim_whitespace=True),
        allow_empty=True,
    )


class RescreenAutoSearchInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    ref_ids = IdListField(required=False, default=list)


class RescreenAIStartInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    ref_ids = IdListField(required=False, default=list)
    ai_model = serializers.CharField(allow_blank=True, required=False, default='')
    ai_models = serializers.ListField(
        child=serializers.CharField(allow_blank=False, trim_whitespace=True),
        required=False,
        default=list,
    )
    enable_thinking = serializers.BooleanField(required=False, default=False)


class RescreenExportInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    scope = serializers.ChoiceField(
        choices=['all', 'included', 'excluded', 'missing_pdf'],
        default='all',
        required=False,
    )


class RescreenReviewInputSerializer(serializers.Serializer):
    human_decision = serializers.ChoiceField(choices=[value for value, _ in RescreenReference.DECISION_CHOICES])
    exclusion_reason = serializers.CharField(allow_blank=True, required=False, default='')
    review_note = serializers.CharField(allow_blank=True, required=False, default='')

    def validate(self, attrs):
        if attrs['human_decision'] == 'excluded' and not attrs.get('exclusion_reason', '').strip():
            raise serializers.ValidationError('排除文献必须填写排除理由')
        return attrs


class RescreenBatchIncludeInputSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1)
    ref_ids = IdListField(required=False, default=list)
