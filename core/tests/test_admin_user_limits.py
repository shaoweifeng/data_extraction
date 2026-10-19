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

    def form_data(
        self, concurrency_limit=2, quota_projects=10,
        quota_storage_mb=5120, quota_storage_mb_override='',
    ):
        return {
            'user': self.user.pk,
            'role': 'user',
            'quota_projects': quota_projects,
            'quota_storage_mb': quota_storage_mb,
            'quota_storage_mb_override': quota_storage_mb_override,
            'is_approved': True,
            'is_banned': False,
            'concurrency_limit': concurrency_limit,
            'approved_at': '',
            'approved_by': '',
        }

    def test_admin_exposes_limits_in_list_and_detail(self):
        profile_admin = UserProfileAdmin(UserProfile, admin.site)
        effective_fields = {
            'current_plan',
            'effective_ai_call_slots',
            'effective_project_limit',
            'storage_usage_display',
        }

        self.assertTrue(effective_fields - {'storage_usage_display'} <= set(profile_admin.list_display))
        self.assertTrue(effective_fields <= set(profile_admin.readonly_fields))
        override_fields = set(dict(profile_admin.fieldsets)['管理员覆盖与存储限制']['fields'])
        self.assertEqual(
            override_fields,
            {'quota_projects_override', 'ai_call_slots_override', 'quota_storage_mb_override'},
        )
        legacy_fields = set(dict(profile_admin.fieldsets)['旧版兼容字段']['fields'])
        self.assertEqual(
            legacy_fields,
            {'quota_projects', 'concurrency_limit', 'quota_storage_mb'},
        )

    def test_admin_accepts_valid_limits(self):
        form = UserProfileAdminForm(
            data=self.form_data(
                concurrency_limit=8,
                quota_projects=25,
                quota_storage_mb_override=10240,
            ),
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.concurrency_limit, 8)
        self.assertEqual(self.profile.quota_projects, 25)
        self.assertEqual(self.profile.quota_storage_mb_override, 10240)

    def test_admin_accepts_unlimited_quota_sentinel(self):
        form = UserProfileAdminForm(
            data=self.form_data(quota_projects=-1, quota_storage_mb_override=-1),
            instance=self.profile,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_rejects_invalid_limits(self):
        cases = (
            ({'concurrency_limit': 0}, 'concurrency_limit'),
            ({'concurrency_limit': 9}, 'concurrency_limit'),
            ({'quota_projects': -2}, 'quota_projects'),
            ({'quota_storage_mb_override': -2}, 'quota_storage_mb_override'),
        )
        for overrides, field_name in cases:
            with self.subTest(overrides=overrides):
                form = UserProfileAdminForm(
                    data=self.form_data(**overrides),
                    instance=self.profile,
                )
                self.assertFalse(form.is_valid())
                self.assertIn(field_name, form.errors)
