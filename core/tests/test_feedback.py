import io
import os
import uuid
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from core.feedback.models import FeedbackAttachment, FeedbackDailyQuota, UserFeedback
from core.models import Project
from core.operations.services import set_system_state


User = get_user_model()


def image_upload(name='screen.png', image_format='PNG'):
    output = io.BytesIO()
    Image.new('RGB', (24, 16), color=(30, 100, 220)).save(output, format=image_format)
    mime = 'image/jpeg' if image_format == 'JPEG' else f'image/{image_format.lower()}'
    return SimpleUploadedFile(name, output.getvalue(), content_type=mime)


class FeedbackApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('feedback-user', password='pw')
        self.other = User.objects.create_user('feedback-other', password='pw')
        self.admin = User.objects.create_user('feedback-admin', password='pw')
        self.admin.profile.role = 'admin'
        self.admin.profile.save(update_fields=['role'])
        self.client.force_login(self.user)

    def tearDown(self):
        set_system_state('normal')

    def submit(self, *, request_id=None, **data):
        payload = {
            'category': 'problem',
            'content': '工作区里的按钮无法正常使用',
            'page_path': '/workspace/1?secret=hidden',
            'route_name': 'Workspace',
            'context': '{"viewport":"1440x900","ignored":"secret"}',
            **data,
        }
        return self.client.post(
            '/api/feedback/',
            payload,
            HTTP_IDEMPOTENCY_KEY=str(request_id or uuid.uuid4()),
        )

    def test_submit_persists_feedback_and_sanitized_context(self):
        response = self.submit()

        self.assertEqual(response.status_code, 201)
        feedback = UserFeedback.objects.get()
        self.assertEqual(feedback.user, self.user)
        self.assertEqual(feedback.reporter_user_id, self.user.id)
        self.assertEqual(feedback.page_path, '/workspace/1')
        self.assertEqual(feedback.context['viewport'], '1440x900')
        self.assertNotIn('ignored', feedback.context)
        self.assertEqual(FeedbackDailyQuota.objects.get(user=self.user).used_count, 1)
        self.assertEqual(response.json()['remaining_today'], 4)

    def test_same_idempotency_key_returns_original_without_using_quota(self):
        request_id = uuid.uuid4()
        first = self.submit(request_id=request_id)
        second = self.submit(request_id=request_id, content='重试时不同的内容也不能覆盖原反馈')

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(UserFeedback.objects.count(), 1)
        self.assertEqual(FeedbackDailyQuota.objects.get(user=self.user).used_count, 1)

    @override_settings(FEEDBACK_DAILY_LIMIT=2, FEEDBACK_BURST_LIMIT=99)
    def test_daily_limit_is_authoritative(self):
        self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(self.submit().status_code, 201)
        response = self.submit()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['code'], 'FEEDBACK_DAILY_LIMIT')
        self.assertEqual(UserFeedback.objects.count(), 2)
        self.assertEqual(FeedbackDailyQuota.objects.get(user=self.user).used_count, 2)

    @override_settings(FEEDBACK_DAILY_LIMIT=10, FEEDBACK_BURST_LIMIT=2)
    def test_burst_limit(self):
        self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(self.submit().status_code, 201)
        response = self.submit()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['code'], 'FEEDBACK_BURST_LIMIT')

    def test_admin_and_anonymous_cannot_submit(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.submit().status_code, 403)
        self.client.logout()
        self.assertEqual(self.submit().status_code, 403)

    def test_project_context_must_be_visible_to_reporter(self):
        project = Project.objects.create(name='别人的项目', owner=self.other)
        response = self.submit(project_id=project.id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'INVALID_PROJECT')
        self.assertEqual(UserFeedback.objects.count(), 0)

    def test_feedback_can_be_submitted_during_maintenance(self):
        set_system_state('maintenance', message='升级中', user=self.admin)
        self.assertEqual(self.submit().status_code, 201)

    def test_user_deletion_keeps_feedback_history(self):
        response = self.submit()
        feedback_id = response.json()['id']
        user_id = self.user.id
        self.user.delete()

        feedback = UserFeedback.objects.get(pk=feedback_id)
        self.assertIsNone(feedback.user)
        self.assertEqual(feedback.reporter_user_id, user_id)

    def test_image_is_reencoded_and_access_is_owner_scoped(self):
        response = self.submit(images=image_upload())
        self.assertEqual(response.status_code, 201, response.content)
        attachment = FeedbackAttachment.objects.get()
        self.assertTrue(attachment.file.storage.exists(attachment.file.name))
        self.assertEqual(attachment.width, 24)
        self.assertEqual(attachment.height, 16)

        url = f'/api/feedback/attachments/{attachment.id}/'
        owner_response = self.client.get(url)
        self.assertEqual(owner_response.status_code, 200)
        owner_response.close()

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.admin)
        admin_response = self.client.get(url)
        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual(admin_response['X-Content-Type-Options'], 'nosniff')
        admin_response.close()

    def test_invalid_image_is_rejected_without_consuming_quota(self):
        fake = SimpleUploadedFile('fake.png', b'<script>alert(1)</script>', content_type='image/png')
        response = self.submit(images=fake)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['code'], 'INVALID_IMAGE')
        self.assertEqual(UserFeedback.objects.count(), 0)
        self.assertEqual(FeedbackDailyQuota.objects.count(), 0)

    def test_storage_failure_rolls_back_feedback_quota_and_written_file(self):
        root = Path(settings.FEEDBACK_UPLOAD_ROOT)
        before = {path for path in root.rglob('*') if path.is_file()} if root.exists() else set()
        with patch('core.feedback.services.FeedbackAttachment.save', side_effect=RuntimeError('disk metadata failure')):
            with self.assertRaisesMessage(RuntimeError, 'disk metadata failure'):
                self.submit(images=image_upload())

        after = {path for path in root.rglob('*') if path.is_file()} if root.exists() else set()
        self.assertEqual(after, before)
        self.assertEqual(UserFeedback.objects.count(), 0)
        self.assertEqual(FeedbackDailyQuota.objects.get(user=self.user).used_count, 0)

    def test_orphan_cleanup_command_is_safe_by_default_and_explicit_on_apply(self):
        orphan = Path(settings.FEEDBACK_UPLOAD_ROOT) / 'orphan' / 'old.png'
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b'orphan')
        old_timestamp = 1_600_000_000
        os.utime(orphan, (old_timestamp, old_timestamp))

        call_command('cleanup_feedback_orphans', older_than_hours=1)
        self.assertTrue(orphan.exists())
        call_command('cleanup_feedback_orphans', apply=True, older_than_hours=1)
        self.assertFalse(orphan.exists())

    def test_idempotency_key_is_required(self):
        response = self.client.post(
            '/api/feedback/',
            {'category': 'problem', 'content': '缺少幂等键的合法反馈'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'INVALID_IDEMPOTENCY_KEY')


class FeedbackAdminDeletionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            'feedback-delete-admin',
            email='feedback-delete-admin@example.com',
            password='pw',
        )
        self.user = User.objects.create_user('feedback-delete-target', password='pw')
        self.quota = FeedbackDailyQuota.objects.create(
            user=self.user,
            quota_date=timezone.localdate(),
            used_count=1,
        )
        self.client.force_login(self.admin)

    def test_user_admin_bulk_delete_cascades_daily_quota(self):
        url = '/admin/auth/user/'
        selection = {
            'action': 'delete_selected',
            '_selected_action': [str(self.user.pk)],
        }

        confirmation = self.client.post(url, selection)

        self.assertEqual(confirmation.status_code, 200)
        self.assertEqual(confirmation.context['perms_lacking'], set())

        response = self.client.post(url, {**selection, 'post': 'yes'})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(FeedbackDailyQuota.objects.filter(pk=self.quota.pk).exists())

    def test_daily_quota_still_cannot_be_deleted_directly(self):
        response = self.client.get(
            f'/admin/feedback/feedbackdailyquota/{self.quota.pk}/delete/',
        )

        self.assertEqual(response.status_code, 403)
