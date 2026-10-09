from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # 注册计费模型的信号处理器（ensure_credit_account）
        import core.models_billing  # noqa: F401
        from core.screening.services.import_limits import validate_import_settings
        from core.quality.services.fulltext import validate_fulltext_settings
        from core.quality.domain import methods as quality_methods  # noqa: F401

        validate_import_settings()
        validate_fulltext_settings()
        import core.screening.signals  # noqa: F401
        import core.quality.signals  # noqa: F401
