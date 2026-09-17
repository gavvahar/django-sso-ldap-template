"""`manage.py check` rules for the LDAP settings.

The same idea as accounts/checks.py, for the other login method: say which
environment variable is missing, rather than letting a half-filled .env look
like a wrong password at the login screen.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def check_ldap_configuration(app_configs, **kwargs):
    """Registered check. Skipped under `manage.py test`, and when LDAP is off,
    so a checkout with no .env still passes."""
    if getattr(settings, "TESTING", False):
        return []
    if not getattr(settings, "AUTH_ENABLE_LDAP", False):
        return []
    return ldap_configuration_problems()


def ldap_configuration_problems():
    """Report missing LDAP settings as errors, and risky ones as warnings."""
    problems = []

    server_uri = getattr(settings, "AUTH_LDAP_SERVER_URI", "")
    if not server_uri:
        problems.append(
            Error(
                "LDAP_SERVER_URI is not set, so LDAP login cannot work.",
                hint="Set it to e.g. ldaps://ldap.example.com:636 in .env. "
                "See .env.example.",
                id="accounts.E010",
            )
        )

    user_search = getattr(settings, "AUTH_LDAP_USER_SEARCH", None)
    if user_search is None or not user_search.base_dn:
        problems.append(
            Error(
                "LDAP_USER_SEARCH_BASE is not set, so users cannot be looked up.",
                hint="Set it to the DN people live under, e.g. "
                "ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com. See docs/ldap.md.",
                id="accounts.E011",
            )
        )

    problems.extend(_group_problems())

    if server_uri.startswith("ldap://") and not getattr(
        settings, "AUTH_LDAP_START_TLS", False
    ):
        problems.append(
            Warning(
                "LDAP_SERVER_URI is plain ldap:// and LDAP_START_TLS is off.",
                hint="The bind password and every user password cross the "
                "network in the clear. Use ldaps:// on port 636, or set "
                "LDAP_START_TLS=true.",
                id="accounts.W010",
            )
        )

    if getattr(settings, "AUTH_LDAP_BIND_DN", "") and not getattr(
        settings, "AUTH_LDAP_BIND_PASSWORD", ""
    ):
        problems.append(
            Warning(
                "LDAP_BIND_DN is set but LDAP_BIND_PASSWORD is empty.",
                hint="Most directories refuse an empty password, which fails "
                "every login at the service bind.",
                id="accounts.W011",
            )
        )

    return problems


# The same variables config/auth_ldap.py reads, named again rather than
# imported: this module is imported from AccountsConfig.ready() whatever the
# toggle says, and importing config.auth_ldap would pull in django-auth-ldap
# (and python-ldap) on a deployment that has neither installed.
GROUP_DN_SETTINGS = {
    "LDAP_REQUIRE_GROUP": "AUTH_LDAP_REQUIRE_GROUP",
    "LDAP_DENY_GROUP": "AUTH_LDAP_DENY_GROUP",
}
GROUP_FLAG_SETTINGS = {
    "LDAP_STAFF_GROUP": "is_staff",
    "LDAP_SUPERUSER_GROUP": "is_superuser",
}


def _group_problems():
    """Group rules match on the full group DN, not on the group's name."""
    problems = []

    named_groups = {}
    for variable, setting in GROUP_DN_SETTINGS.items():
        value = getattr(settings, setting, "")
        if value:
            named_groups[variable] = value
    flags_by_group = getattr(settings, "AUTH_LDAP_USER_FLAGS_BY_GROUP", {})
    for variable, flag in GROUP_FLAG_SETTINGS.items():
        if flags_by_group.get(flag):
            named_groups[variable] = flags_by_group[flag]

    # A group rule with no group search cannot reach here: config/auth_ldap.py
    # refuses that combination at startup.
    for variable, value in sorted(named_groups.items()):
        if "=" not in value:
            problems.append(
                Warning(
                    f"{variable} is {value!r}, which is not a DN.",
                    hint="These settings match on the full group DN, e.g. "
                    f"cn={value},ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com.",
                    id="accounts.W012",
                )
            )

    return problems
