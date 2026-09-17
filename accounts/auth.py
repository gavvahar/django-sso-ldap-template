"""OIDC authentication backend and provider logout helper.

Subclasses mozilla-django-oidc's backend to map Authentik's claims onto the
Django user: a readable username, name and email, and optionally group
membership and the staff/superuser flags.
"""

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.models import Group
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.utils import absolutify

LOGGER = logging.getLogger(__name__)


class OIDCBackend(OIDCAuthenticationBackend):
    """Authenticate against an OpenID Connect provider (Authentik by default)."""

    def get_username(self, claims):
        """Prefer the provider's username claim over a hash of the email."""
        username = claims.get(settings.OIDC_USERNAME_CLAIM) or ""
        if username:
            return username[:150]
        email = claims.get("email") or ""
        if email:
            return email.split("@")[0][:150]
        return super().get_username(claims)

    def create_user(self, claims):
        user = super().create_user(claims)
        return self.update_user(user, claims)

    def update_user(self, user, claims):
        """Copy claims onto the user on every login, so the IdP stays the source
        of truth for names, email and group membership."""
        user.username = self.get_username(claims)
        user.email = claims.get("email", user.email)
        user.first_name = (claims.get("given_name") or "")[:150]
        user.last_name = (claims.get("family_name") or "")[:150]

        if not user.first_name and not user.last_name:
            # Authentik sends a single `name` claim when the user has no
            # separate given/family name set.
            name = (claims.get("name") or "").strip()
            if name:
                first, _, last = name.partition(" ")
                user.first_name, user.last_name = first[:150], last[:150]

        groups = self._claimed_groups(claims)
        if settings.OIDC_STAFF_GROUP:
            user.is_staff = settings.OIDC_STAFF_GROUP in groups
        if settings.OIDC_SUPERUSER_GROUP:
            user.is_superuser = settings.OIDC_SUPERUSER_GROUP in groups

        user.save()

        if settings.OIDC_SYNC_GROUPS:
            self._sync_groups(user, groups)

        return user

    def _claimed_groups(self, claims):
        """Return the group names from the provider, normalised to a list."""
        groups = claims.get(settings.OIDC_GROUPS_CLAIM, [])
        if isinstance(groups, str):
            groups = [groups]
        return [str(group) for group in groups]

    def _sync_groups(self, user, group_names):
        """Make the user's Django groups match the provider's group claim.

        Groups that do not exist in Django yet are created, so permissions can
        be granted to them in the admin without any extra wiring.
        """
        groups = [Group.objects.get_or_create(name=name)[0] for name in group_names]
        user.groups.set(groups)


def provider_logout_url(request):
    """Build the provider's RP-initiated logout URL for the current session.

    Called by mozilla-django-oidc's logout view. Falls back to Django's own
    LOGOUT_REDIRECT_URL when the provider has no end-session endpoint
    configured, which keeps local logout working before SSO is set up.
    """
    end_session = getattr(settings, "OIDC_OP_LOGOUT_ENDPOINT", "")
    redirect_to = absolutify(request, settings.LOGOUT_REDIRECT_URL)
    if not end_session:
        return redirect_to

    params = {"post_logout_redirect_uri": redirect_to}
    id_token = request.session.get("oidc_id_token")
    if id_token:
        params["id_token_hint"] = id_token
    else:
        # Without a hint the provider will ask the user to confirm the logout.
        LOGGER.debug("No stored id token; provider will confirm logout with the user.")
        params["client_id"] = settings.OIDC_RP_CLIENT_ID

    return f"{end_session}?{urlencode(params)}"
