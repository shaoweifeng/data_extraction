from rest_framework import serializers
from .models import Project, Document, ExtractionTask, Stage, StageData
from django.contrib.auth.models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = '__all__'

class ExtractionTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractionTask
        fields = '__all__'

class StageDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = StageData
        fields = '__all__'

class StageSerializer(serializers.ModelSerializer):
    data = StageDataSerializer(many=True, read_only=True)

    class Meta:
        model = Stage
        fields = ['id', 'project', 'stage_type', 'status', 'updated_at', 'data']

class ProjectSerializer(serializers.ModelSerializer):
    documents_count = serializers.IntegerField(source='documents.count', read_only=True)
    latest_task_status = serializers.SerializerMethodField()
    stages = StageSerializer(many=True, read_only=True)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'creator', 'created_at', 'updated_at', 'documents_count', 'latest_task_status', 'stages']

    def get_latest_task_status(self, obj):
        latest_task = obj.tasks.order_by('-created_at').first()
        return latest_task.status if latest_task else None
