from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.account'
    label = 'account'
    verbose_name = '账户与身份'

    def ready(self):
        from . import checks  # noqa: F401
