"""Django Admin user quota and concurrency configuration tests."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.admin import UserProfileAdmin, UserProfileAdminForm
from core.models import UserProfile


User = get_user_model()


@override_settings(AI_SCREEN_MAX_GLOBAL_THREADS=8)
class UserProfileLimitsAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('limits-user')
        self.profile = self.user.profile

    def form_data(self, concurrency_limit=2, quota_projects=10, quota_storage_mb=5120):
        return {
            'user': self.user.pk,
            'role': 'user',
            'quota_projects': quota_projects,
            'quota_storage_mb': quota_storage_mb,
            'is_approved': True,
            'is_banned': False,
            'concurrency_limit': concurrency_limit,
            'approved_at': '',
            'approved_by': '',
        }

    def test_admin_exposes_limits_in_list_and_detail(self):
        profile_admin = UserProfileAdmin(UserProfile, admin.site)
        editable_limits = {
            'concurrency_limit',
            'quota_projects',
            'quota_storage_mb',
        }

        self.assertTrue(editable_limits.issubset(profile_admin.list_display))
        self.assertTrue(editable_limits.issubset(profile_admin.list_editable))
        quota_fields = set(dict(profile_admin.fieldsets)['配额设置']['fields'])
        self.assertTrue(editable_limits.issubset(quota_fields))

    def test_admin_accepts_valid_limits(self):
        form = UserProfileAdminForm(
            data=self.form_data(
                concurrency_limit=8,
                quota_projects=25,
                quota_storage_mb=10240,
            ),
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.concurrency_limit, 8)
        self.assertEqual(self.profile.quota_projects, 25)
        self.assertEqual(self.profile.quota_storage_mb, 10240)

    def test_admin_accepts_unlimited_quota_sentinel(self):
        form = UserProfileAdminForm(
            data=self.form_data(quota_projects=-1, quota_storage_mb=-1),
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_rejects_invalid_limits(self):
        cases = (
            ({'concurrency_limit': 0}, 'concurrency_limit'),
            ({'concurrency_limit': 9}, 'concurrency_limit'),
            ({'quota_projects': -2}, 'quota_projects'),
            ({'quota_storage_mb': -2}, 'quota_storage_mb'),
        )
        for overrides, field_name in cases:
            with self.subTest(overrides=overrides):
                form = UserProfileAdminForm(
                    data=self.form_data(**overrides),
                    instance=self.profile,
                )
                self.assertFalse(form.is_valid())
                self.assertIn(field_name, form.errors)
