from django.urls import path

from .api.authentication_views import login_view
from .api.legal_views import current_legal_document_list, legal_document_detail
from .api.security_views import (
    change_password_view,
    confirm_email_change_view,
    forgot_password,
    request_email_change,
    reset_password_view,
)
from .api.verification_views import resend_verification_email, verify_email
from .api.views import register

urlpatterns = [
    path('register/', register, name='register'),
    path('login/', login_view, name='login'),
    path('legal/current/', current_legal_document_list, name='current_legal_documents'),
    path('legal/<str:document_type>/', legal_document_detail, name='legal_document_detail'),
    path('email/verify/', verify_email, name='verify_email'),
    path('email/resend/', resend_verification_email, name='resend_verification_email'),
    path('email/change/request/', request_email_change, name='request_email_change'),
    path('email/change/confirm/', confirm_email_change_view, name='confirm_email_change'),
    path('password/forgot/', forgot_password, name='forgot_password'),
    path('password/reset/', reset_password_view, name='reset_password'),
    path('password/change/', change_password_view, name='change_password'),
]
