from django.urls import path

from .api_views import external_image_upload


app_name = 'external_images'

urlpatterns = [
    path('', external_image_upload, name='upload'),
]
