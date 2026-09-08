"""初筛人工审阅 API 请求参数校验器。"""

from rest_framework import serializers

from core.models import ManualReview


DECISION_CHOICES = [value for value, _ in ManualReview.DECISION_CHOICES]


class ReviewItemInputSerializer(serializers.Serializer):
    source_xml = serializers.CharField(max_length=500)
    decision = serializers.ChoiceField(choices=DECISION_CHOICES)
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class ReviewSubmitInputSerializer(serializers.Serializer):
    project = serializers.IntegerField(min_value=1)
    step = serializers.IntegerField(min_value=1)
    reviews = ReviewItemInputSerializer(many=True, allow_empty=False)


class ReviewUpdateInputSerializer(serializers.Serializer):
    project = serializers.IntegerField(min_value=1)
    step = serializers.IntegerField(min_value=1)
    decision = serializers.ChoiceField(choices=DECISION_CHOICES)
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class ReviewCompleteInputSerializer(serializers.Serializer):
    project = serializers.IntegerField(min_value=1)
    step = serializers.IntegerField(min_value=1)


class ReviewNoteInputSerializer(ReviewCompleteInputSerializer):
    content = serializers.CharField(max_length=5000, trim_whitespace=True)
