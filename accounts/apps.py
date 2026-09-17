from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Registers the `manage.py check` rules for the SSO configuration.
        from . import checks  # noqa: F401
