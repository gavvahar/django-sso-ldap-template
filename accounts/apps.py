from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Registers the `manage.py check` rules for the SSO and LDAP settings.
        # Each stands down when its own login method is switched off.
        from . import checks, ldap_checks  # noqa: F401
