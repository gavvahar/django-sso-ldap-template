"""Django settings for the SSO starter template.

Everything environment-specific is read from the environment (see .env.example).
Nothing in this file needs editing to point the template at your own provider.
"""

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .env import env, env_bool, env_int, env_list
from .oidc import endpoints_from_issuer

BASE_DIR = Path(__file__).resolve().parent.parent

# True while the test suite runs, under either `manage.py test` or pytest; the
# OIDC configuration checks stand down so the suite passes with no .env.
TESTING = (
    "test" in sys.argv
    or "PYTEST_VERSION" in os.environ
    or Path(sys.argv[0]).name.startswith("pytest")
)

# --- Core Django -----------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-development-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mozilla_django_oidc",
    "accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Re-checks the session against the provider once the id token has aged out, so
# that a user disabled in Authentik loses access without waiting for the Django
# session to expire.
if env_bool("AUTH_ENABLE_OIDC", True) and env_bool("OIDC_RENEW_SESSION", True):
    MIDDLEWARE.append("mozilla_django_oidc.middleware.SessionRefresh")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Serves the collected files straight from the application, so a container
# running gunicorn needs no web server in front of it for /static/ -- the
# admin's CSS above all. It goes directly after SecurityMiddleware, as
# whitenoise requires, and stands down until `manage.py collectstatic` has run
# (the Docker image runs it at build time): before that there is nothing to
# serve, and `runserver` serves static files itself while DEBUG is on.
if STATIC_ROOT.is_dir():
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Behind a TLS-terminating proxy the redirect_uri must still be built as https.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- Authentication --------------------------------------------------------

# Each login method is switched on independently, so a deployment can run SSO
# only, local passwords only, or both. Additional backends (e.g. LDAP) append
# themselves to this list.
AUTH_ENABLE_OIDC = env_bool("AUTH_ENABLE_OIDC", True)
# Local passwords keep `manage.py createsuperuser` accounts able to reach
# /admin/ when the provider is unreachable. Turn off to make SSO the only way in.
AUTH_ENABLE_LOCAL_PASSWORDS = env_bool("AUTH_ENABLE_LOCAL_PASSWORDS", True)
# Off by default: django-auth-ldap and its python-ldap dependency are installed
# separately (requirements-ldap.txt), because python-ldap needs system
# libraries to build. See docs/ldap.md.
AUTH_ENABLE_LDAP = env_bool("AUTH_ENABLE_LDAP", False)

AUTHENTICATION_BACKENDS = []
if AUTH_ENABLE_OIDC:
    AUTHENTICATION_BACKENDS.append("accounts.auth.OIDCBackend")
if AUTH_ENABLE_LDAP:
    AUTHENTICATION_BACKENDS.append("django_auth_ldap.backend.LDAPBackend")
# Last, so a directory account is authenticated against the directory rather
# than against a stale password hash in the local database.
if AUTH_ENABLE_LOCAL_PASSWORDS:
    AUTHENTICATION_BACKENDS.append("django.contrib.auth.backends.ModelBackend")
if not AUTHENTICATION_BACKENDS:
    raise ImproperlyConfigured(
        "No authentication backend is enabled: set AUTH_ENABLE_OIDC, "
        "AUTH_ENABLE_LDAP or AUTH_ENABLE_LOCAL_PASSWORDS to true."
    )

LOGIN_URL = "oidc_authentication_init"
LOGIN_REDIRECT_URL = env("LOGIN_REDIRECT_URL", "/")
LOGIN_REDIRECT_URL_FAILURE = env("LOGIN_REDIRECT_URL_FAILURE", "/")
LOGOUT_REDIRECT_URL = env("LOGOUT_REDIRECT_URL", "/")

# --- OpenID Connect (Authentik) --------------------------------------------

OIDC_ISSUER = env("OIDC_ISSUER", "")
_endpoints = endpoints_from_issuer(OIDC_ISSUER)

OIDC_RP_CLIENT_ID = env("OIDC_RP_CLIENT_ID", "")
OIDC_RP_CLIENT_SECRET = env("OIDC_RP_CLIENT_SECRET", "")
OIDC_RP_SCOPES = env("OIDC_RP_SCOPES", "openid email profile")
OIDC_RP_SIGN_ALGO = env("OIDC_RP_SIGN_ALGO", "RS256")

OIDC_OP_AUTHORIZATION_ENDPOINT = env(
    "OIDC_OP_AUTHORIZATION_ENDPOINT", _endpoints["authorization_endpoint"]
)
OIDC_OP_TOKEN_ENDPOINT = env("OIDC_OP_TOKEN_ENDPOINT", _endpoints["token_endpoint"])
OIDC_OP_USER_ENDPOINT = env("OIDC_OP_USER_ENDPOINT", _endpoints["userinfo_endpoint"])
OIDC_OP_JWKS_ENDPOINT = env("OIDC_OP_JWKS_ENDPOINT", _endpoints["jwks_uri"])
OIDC_OP_LOGOUT_ENDPOINT = env(
    "OIDC_OP_LOGOUT_ENDPOINT", _endpoints["end_session_endpoint"]
)

# Ends the session at the provider too, not just in Django.
OIDC_OP_LOGOUT_URL_METHOD = "accounts.auth.provider_logout_url"
OIDC_STORE_ID_TOKEN = True  # required to send id_token_hint on logout

OIDC_USE_PKCE = env_bool("OIDC_USE_PKCE", True)
OIDC_CREATE_USER = env_bool("OIDC_CREATE_USER", True)
OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS = env_int("OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS", 900)

# Claim-to-user mapping, all optional.
OIDC_USERNAME_CLAIM = env("OIDC_USERNAME_CLAIM", "preferred_username")
OIDC_GROUPS_CLAIM = env("OIDC_GROUPS_CLAIM", "groups")
OIDC_SYNC_GROUPS = env_bool("OIDC_SYNC_GROUPS", True)
OIDC_STAFF_GROUP = env("OIDC_STAFF_GROUP", "")
OIDC_SUPERUSER_GROUP = env("OIDC_SUPERUSER_GROUP", "")

# --- LDAP ------------------------------------------------------------------

# Imported only when enabled, so django-auth-ldap stays an optional dependency.
# Every AUTH_LDAP_* setting is derived from the environment; see docs/ldap.md.
if AUTH_ENABLE_LDAP:
    from .auth_ldap import *  # noqa: E402,F401,F403

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "mozilla_django_oidc": {
            "handlers": ["console"],
            "level": env("OIDC_LOG_LEVEL", "INFO"),
        },
        "accounts": {"handlers": ["console"], "level": env("OIDC_LOG_LEVEL", "INFO")},
        # Says why a login was refused; without it a misconfigured directory
        # looks exactly like a wrong password.
        "django_auth_ldap": {
            "handlers": ["console"],
            "level": env("LDAP_LOG_LEVEL", "WARNING"),
        },
    },
}
