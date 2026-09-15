from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from ..email import normalize_email_address
from ..models import AccountEmail

User = get_user_model()


class RegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    email = serializers.CharField(max_length=254, trim_whitespace=True)
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    password_confirm = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate_username(self, value):
        value = value.strip()
        field = User._meta.get_field('username')
        for validator in field.validators:
            validator(value)
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('用户名已存在', code='username_taken')
        return value

    def validate_email(self, value):
        try:
            normalized = normalize_email_address(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError('请输入有效的邮箱地址', code='invalid_email') from exc
        if (
            AccountEmail.objects.filter(normalized_email=normalized).exists()
            or User.objects.filter(email__iexact=normalized).exists()
        ):
            raise serializers.ValidationError('邮箱已被使用', code='email_taken')
        return normalized

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError(
                {'password_confirm': '两次输入的密码不一致'},
                code='password_mismatch',
            )

        min_length = getattr(settings, 'ACCOUNT_PASSWORD_MIN_LENGTH', 8)
        if len(attrs['password']) < min_length:
            raise serializers.ValidationError(
                {'password': f'密码长度不能少于 {min_length} 个字符'},
                code='password_too_short',
            )
        max_length = getattr(settings, 'ACCOUNT_PASSWORD_MAX_LENGTH', 128)
        if len(attrs['password']) > max_length:
            raise serializers.ValidationError(
                {'password': f'密码长度不能超过 {max_length} 个字符'},
                code='password_too_long',
            )

        candidate = User(username=attrs['username'], email=attrs['email'])
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)}) from exc
        return attrs


class EmailVerificationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=256, trim_whitespace=True)


class VerificationResendSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=254, trim_whitespace=True)

    def validate_email(self, value):
        try:
            return normalize_email_address(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError('请输入有效的邮箱地址') from exc
