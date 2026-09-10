from django.apps import AppConfig


class FeedbackConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.feedback'
    label = 'feedback'
    verbose_name = '用户反馈'

    def ready(self):
        import core.feedback.signals  # noqa: F401

