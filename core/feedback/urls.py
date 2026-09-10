from django.urls import path

from .api_views import feedback_attachment, feedback_submit


app_name = 'feedback'

urlpatterns = [
    path('', feedback_submit, name='submit'),
    path('attachments/<uuid:attachment_id>/', feedback_attachment, name='attachment'),
]

