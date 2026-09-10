import json

from django.conf import settings
from rest_framework import serializers


class FeedbackSubmissionSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=('problem', 'suggestion'))
    content = serializers.CharField(trim_whitespace=True)
    project_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    page_path = serializers.CharField(required=False, allow_blank=True, max_length=500)
    route_name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    context = serializers.JSONField(required=False, default=dict)

    def validate_content(self, value):
        length = len(value)
        minimum = settings.FEEDBACK_CONTENT_MIN_LENGTH
        maximum = settings.FEEDBACK_CONTENT_MAX_LENGTH
        if length < minimum or length > maximum:
            raise serializers.ValidationError(f'反馈内容须为 {minimum}～{maximum} 个字符')
        return value

    def validate_page_path(self, value):
        value = value.split('?', 1)[0].split('#', 1)[0]
        return value if value.startswith('/') else ''

    def validate_context(self, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError('context 必须是合法 JSON') from exc
        if not isinstance(value, dict):
            raise serializers.ValidationError('context 必须是对象')

        allowed = ('viewport', 'browser', 'platform', 'frontend_version')
        cleaned = {key: str(value[key])[:200] for key in allowed if value.get(key)}
        if len(json.dumps(cleaned, ensure_ascii=False).encode('utf-8')) > 4096:
            raise serializers.ValidationError('context 内容过大')
        return cleaned

