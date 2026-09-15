from django.urls import path

from .api.verification_views import resend_verification_email, verify_email
from .api.views import register

urlpatterns = [
    path('register/', register, name='register'),
    path('email/verify/', verify_email, name='verify_email'),
    path('email/resend/', resend_verification_email, name='resend_verification_email'),
]
