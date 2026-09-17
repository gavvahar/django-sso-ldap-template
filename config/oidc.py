"""Derive OpenID Connect endpoint URLs from a provider issuer URL.

The template is aimed at Authentik, whose issuer for an OAuth2/OIDC provider
looks like ``https://authentik.example.com/application/o/<app-slug>/``. Every
endpoint below can be overridden individually in ``.env`` if your provider
lays its URLs out differently, so this is only a convenience default.

``manage.py oidc_discover`` fetches the provider's discovery document and
prints the exact values, which is the authoritative source if in doubt.
"""

from urllib.parse import urljoin

# Maps the setting suffix used by mozilla-django-oidc to the key the provider
# uses for the same endpoint in its .well-known/openid-configuration document.
ENDPOINT_KEYS = {
    "authorization_endpoint": "OIDC_OP_AUTHORIZATION_ENDPOINT",
    "token_endpoint": "OIDC_OP_TOKEN_ENDPOINT",
    "userinfo_endpoint": "OIDC_OP_USER_ENDPOINT",
    "jwks_uri": "OIDC_OP_JWKS_ENDPOINT",
    "end_session_endpoint": "OIDC_OP_LOGOUT_ENDPOINT",
}


def endpoints_from_issuer(issuer):
    """Return Authentik's conventional endpoint URLs for ``issuer``.

    Authentik serves the authorization, token and userinfo endpoints from the
    shared ``/application/o/`` root and the per-application JWKS and
    end-session endpoints from below the issuer URL itself. Returns empty
    strings when no issuer is configured, so that Django can still start (and
    ``manage.py check`` can report what is missing) on a fresh checkout.
    """
    if not issuer:
        return dict.fromkeys(ENDPOINT_KEYS, "")

    issuer = issuer if issuer.endswith("/") else issuer + "/"
    provider_root = urljoin(issuer, "../")  # strip the application slug

    return {
        "authorization_endpoint": urljoin(provider_root, "authorize/"),
        "token_endpoint": urljoin(provider_root, "token/"),
        "userinfo_endpoint": urljoin(provider_root, "userinfo/"),
        "jwks_uri": urljoin(issuer, "jwks/"),
        "end_session_endpoint": urljoin(issuer, "end-session/"),
    }
