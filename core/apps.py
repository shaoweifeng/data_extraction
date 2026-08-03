from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # 注册计费模型的信号处理器（ensure_credit_account）
        import core.models_billing  # noqa: F401
