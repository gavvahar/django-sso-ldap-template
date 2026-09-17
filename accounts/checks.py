"""Startup checks that turn a half-configured .env into a clear error message.

Run with `manage.py check`; Django also runs them before `runserver`.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register

REQUIRED = {
    "OIDC_RP_CLIENT_ID": "the Client ID from the Authentik provider",
    "OIDC_RP_CLIENT_SECRET": "the Client Secret from the Authentik provider",
    "OIDC_OP_AUTHORIZATION_ENDPOINT": "OIDC_ISSUER, or this endpoint directly",
    "OIDC_OP_TOKEN_ENDPOINT": "OIDC_ISSUER, or this endpoint directly",
    "OIDC_OP_USER_ENDPOINT": "OIDC_ISSUER, or this endpoint directly",
    "OIDC_OP_JWKS_ENDPOINT": "OIDC_ISSUER, or this endpoint directly",
}


@register()
def check_oidc_configuration(app_configs, **kwargs):
    """Registered check. Skipped under `manage.py test`, so that a fresh
    checkout can run its tests before any provider has been configured."""
    if getattr(settings, "TESTING", False):
        return []
    if not getattr(settings, "AUTH_ENABLE_OIDC", True):
        return []
    return oidc_configuration_problems()


def oidc_configuration_problems():
    """Report missing OIDC settings as errors, and insecure ones as warnings."""
    problems = []

    for setting, hint in REQUIRED.items():
        if not getattr(settings, setting, ""):
            problems.append(
                Error(
                    f"{setting} is not set, so SSO login cannot work.",
                    hint=f"Set {hint} in .env. See .env.example.",
                    id="accounts.E001",
                )
            )

    if "openid" not in settings.OIDC_RP_SCOPES.split():
        problems.append(
            Error(
                "OIDC_RP_SCOPES must include the 'openid' scope.",
                id="accounts.E002",
            )
        )

    issuer = getattr(settings, "OIDC_ISSUER", "")
    if issuer and not issuer.startswith("https://"):
        problems.append(
            Warning(
                "OIDC_ISSUER is not an https:// URL.",
                hint="Tokens and the client secret travel over this connection.",
                id="accounts.W001",
            )
        )

    return problems
