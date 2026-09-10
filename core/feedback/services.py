from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.services.access_policy import ProjectAccessPolicy

from .models import FeedbackAttachment, FeedbackDailyQuota, UserFeedback


class FeedbackLimitExceeded(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass
class FeedbackSubmissionResult:
    feedback: UserFeedback
    remaining_today: int
    created: bool


def submit_feedback(*, user, client_request_id, data, images, user_agent=''):
    quota_date = timezone.localdate()
    FeedbackDailyQuota.objects.get_or_create(user=user, quota_date=quota_date)
    saved_files = []

    try:
        with transaction.atomic():
            quota = FeedbackDailyQuota.objects.select_for_update().get(
                user=user,
                quota_date=quota_date,
            )
            existing = UserFeedback.objects.filter(
                reporter_user_id=user.id,
                client_request_id=client_request_id,
            ).first()
            if existing:
                return FeedbackSubmissionResult(
                    feedback=existing,
                    remaining_today=max(0, settings.FEEDBACK_DAILY_LIMIT - quota.used_count),
                    created=False,
                )

            if quota.used_count >= settings.FEEDBACK_DAILY_LIMIT:
                raise FeedbackLimitExceeded('FEEDBACK_DAILY_LIMIT', '今日反馈次数已用完，请明天再试')

            burst_since = timezone.now() - timedelta(seconds=settings.FEEDBACK_BURST_WINDOW_SECONDS)
            recent_count = UserFeedback.objects.filter(user=user, created_at__gte=burst_since).count()
            if recent_count >= settings.FEEDBACK_BURST_LIMIT:
                raise FeedbackLimitExceeded('FEEDBACK_BURST_LIMIT', '提交过于频繁，请稍后再试')

            project = None
            if data.get('project_id'):
                project = ProjectAccessPolicy.get_project(user, data['project_id'])
                if project is None:
                    raise ValueError('关联项目不存在或无权访问')

            context = dict(data.get('context') or {})
            if user_agent:
                context['user_agent'] = user_agent[:500]
            feedback = UserFeedback.objects.create(
                user=user,
                reporter_user_id=user.id,
                reporter_username=user.get_username(),
                category=data['category'],
                content=data['content'],
                project=project,
                page_path=data.get('page_path', ''),
                route_name=data.get('route_name', ''),
                client_request_id=client_request_id,
                context=context,
            )

            for image in images:
                attachment = FeedbackAttachment(
                    feedback=feedback,
                    original_name=image.original_name,
                    mime_type=image.mime_type,
                    file_size=image.file_size,
                    sha256=image.sha256,
                    width=image.width,
                    height=image.height,
                )
                attachment.file.save(image.content.name, image.content, save=False)
                saved_files.append((attachment.file.storage, attachment.file.name))
                attachment.save()

            quota.used_count += 1
            quota.save(update_fields=['used_count', 'updated_at'])
            remaining = max(0, settings.FEEDBACK_DAILY_LIMIT - quota.used_count)
        return FeedbackSubmissionResult(feedback=feedback, remaining_today=remaining, created=True)
    except Exception:
        for storage, name in saved_files:
            storage.delete(name)
        raise
