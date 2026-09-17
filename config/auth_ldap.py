"""LDAP settings, read from the environment.

Imported by ``config/settings.py`` only when ``AUTH_ENABLE_LDAP`` is true::

    if AUTH_ENABLE_LDAP:
        from .auth_ldap import *  # noqa: F401,F403

so a deployment that does not use a directory never imports django-auth-ldap
and never needs python-ldap's system libraries.

Settings that are simply not filled in yet are left blank here and reported by
``manage.py check`` (see ``accounts/ldap_checks.py``), matching how the OIDC
settings behave. Values that are filled in but malformed -- an unknown group
type, a search scope that is not a scope -- raise ``ImproperlyConfigured``,
because there is no sensible value to carry forward.

Every ``AUTH_LDAP_*`` name django-auth-ldap reads is documented at
https://django-auth-ldap.readthedocs.io/; ``docs/ldap.md`` covers the
environment variables and a JumpCloud walkthrough.
"""

import ldap
from django.core.exceptions import ImproperlyConfigured
from django_auth_ldap import config as ldap_config

from .env import env, env_bool, env_int, env_list

# Group classes django-auth-ldap ships, keyed by the name used in
# LDAP_GROUP_TYPE, with the objectClass each one is stored under so the group
# filter has a sensible default. "groupOfNames" covers JumpCloud, OpenLDAP and
# FreeIPA. The "nested" variants follow group-in-group membership, at the cost
# of extra queries per login.
GROUP_TYPES = {
    "groupOfNames": ("GroupOfNamesType", "groupOfNames"),
    "nestedGroupOfNames": ("NestedGroupOfNamesType", "groupOfNames"),
    "groupOfUniqueNames": ("GroupOfUniqueNamesType", "groupOfUniqueNames"),
    "nestedGroupOfUniqueNames": (
        "NestedGroupOfUniqueNamesType",
        "groupOfUniqueNames",
    ),
    "posixGroup": ("PosixGroupType", "posixGroup"),
    "organizationalRole": ("OrganizationalRoleGroupType", "organizationalRole"),
    "nestedOrganizationalRole": (
        "NestedOrganizationalRoleGroupType",
        "organizationalRole",
    ),
    "activeDirectory": ("ActiveDirectoryGroupType", "group"),
    "nestedActiveDirectory": ("NestedActiveDirectoryGroupType", "group"),
}

SCOPES = {
    "base": ldap.SCOPE_BASE,
    "onelevel": ldap.SCOPE_ONELEVEL,
    "subtree": ldap.SCOPE_SUBTREE,
}

DEFAULT_USER_SEARCH_FILTER = "(&(objectClass=inetOrgPerson)(uid=%(user)s))"
DEFAULT_USER_ATTR_MAP = "first_name=givenName,last_name=sn,email=mail"


def ldap_settings():
    """Build the ``AUTH_LDAP_*`` settings dict from the environment."""
    settings = {
        "AUTH_LDAP_SERVER_URI": env("LDAP_SERVER_URI", ""),
        # Blank means an anonymous bind, which some directories allow for
        # lookups. JumpCloud does not; it wants a real service user.
        "AUTH_LDAP_BIND_DN": env("LDAP_BIND_DN", ""),
        # Not stripped: a password may legitimately start or end with a space.
        "AUTH_LDAP_BIND_PASSWORD": env("LDAP_BIND_PASSWORD", ""),
        "AUTH_LDAP_START_TLS": env_bool("LDAP_START_TLS", False),
        "AUTH_LDAP_USER_SEARCH": ldap_config.LDAPSearch(
            env("LDAP_USER_SEARCH_BASE", ""),
            _scope("LDAP_USER_SEARCH_SCOPE"),
            env("LDAP_USER_SEARCH_FILTER", DEFAULT_USER_SEARCH_FILTER),
        ),
        "AUTH_LDAP_USER_ATTR_MAP": _attr_map(),
        "AUTH_LDAP_ALWAYS_UPDATE_USER": env_bool("LDAP_ALWAYS_UPDATE_USER", True),
        "AUTH_LDAP_CONNECTION_OPTIONS": _connection_options(),
        # Group membership is otherwise re-read on every permission check.
        "AUTH_LDAP_CACHE_TIMEOUT": _int("LDAP_CACHE_TIMEOUT", 3600),
    }
    settings.update(_group_settings())
    return settings


def _int(name, default):
    try:
        return env_int(name, default)
    except ValueError:
        raise ImproperlyConfigured(
            f"{name} must be a whole number, got {env(name, '')!r}."
        ) from None


def _scope(name):
    value = env(name, "subtree").strip().lower()
    if value not in SCOPES:
        raise ImproperlyConfigured(
            f"{name} must be one of {', '.join(sorted(SCOPES))}, got {value!r}."
        )
    return SCOPES[value]


def _attr_map():
    """Parse ``django_field=ldapAttribute`` pairs into a dict."""
    mapping = {}
    for entry in env_list("LDAP_USER_ATTR_MAP", DEFAULT_USER_ATTR_MAP):
        if "=" not in entry:
            raise ImproperlyConfigured(
                "LDAP_USER_ATTR_MAP entries must look like "
                f"'django_field=ldapAttribute', got {entry!r}."
            )
        field, _, attribute = entry.partition("=")
        mapping[field.strip()] = attribute.strip()
    return mapping


# The variables that name a group: the two access rules, and the two that grant
# a Django flag. All of them need a group search to match against.
GROUP_DN_VARIABLES = {
    "LDAP_REQUIRE_GROUP": "AUTH_LDAP_REQUIRE_GROUP",
    "LDAP_DENY_GROUP": "AUTH_LDAP_DENY_GROUP",
}
GROUP_FLAG_VARIABLES = {
    "LDAP_STAFF_GROUP": "is_staff",
    "LDAP_SUPERUSER_GROUP": "is_superuser",
}


def _group_settings():
    """Group search, group-to-Django-group mirroring, and access rules.

    Returns nothing at all when no group base is configured, so a directory
    whose groups are elsewhere (or absent) still authenticates users.
    """
    base_dn = env("LDAP_GROUP_SEARCH_BASE", "")
    if not base_dn:
        # Without a group base none of these can ever match, and a
        # LDAP_STAFF_GROUP that silently grants nobody staff is worse than a
        # startup error.
        orphaned = [
            variable
            for variable in (*GROUP_DN_VARIABLES, *GROUP_FLAG_VARIABLES)
            if env(variable, "")
        ]
        if orphaned:
            raise ImproperlyConfigured(
                f"{', '.join(orphaned)} names a group, but "
                "LDAP_GROUP_SEARCH_BASE is not set, so no group is ever looked "
                "up. On JumpCloud it is the same DN as LDAP_USER_SEARCH_BASE."
            )
        return {}

    type_name = env("LDAP_GROUP_TYPE", "groupOfNames").strip()
    if type_name not in GROUP_TYPES:
        raise ImproperlyConfigured(
            "LDAP_GROUP_TYPE must be one of "
            f"{', '.join(sorted(GROUP_TYPES))}, got {type_name!r}."
        )
    class_name, object_class = GROUP_TYPES[type_name]

    settings = {
        "AUTH_LDAP_GROUP_SEARCH": ldap_config.LDAPSearch(
            base_dn,
            _scope("LDAP_GROUP_SEARCH_SCOPE"),
            env("LDAP_GROUP_SEARCH_FILTER", f"(objectClass={object_class})"),
        ),
        "AUTH_LDAP_GROUP_TYPE": getattr(ldap_config, class_name)(name_attr="cn"),
        # Off by default: it makes every permission check consult the group
        # tree, which is rarely what a new project wants on day one.
        "AUTH_LDAP_FIND_GROUP_PERMS": env_bool("LDAP_FIND_GROUP_PERMS", False),
    }

    # Mirroring copies directory groups onto the Django user at every login, so
    # membership is owned by the directory. Naming groups in
    # LDAP_MIRROR_GROUPS_ONLY narrows that to a subset and leaves every other
    # Django group managed locally.
    mirror_only = env_list("LDAP_MIRROR_GROUPS_ONLY")
    settings["AUTH_LDAP_MIRROR_GROUPS"] = mirror_only or env_bool(
        "LDAP_MIRROR_GROUPS", True
    )

    for variable, setting in GROUP_DN_VARIABLES.items():
        value = env(variable, "")
        if value:
            settings[setting] = value

    flags = {}
    for variable, flag in GROUP_FLAG_VARIABLES.items():
        value = env(variable, "")
        if value:
            flags[flag] = value
    if flags:
        settings["AUTH_LDAP_USER_FLAGS_BY_GROUP"] = flags

    return settings


def _connection_options():
    """Timeouts and TLS verification, as python-ldap option codes."""
    timeout = _int("LDAP_CONNECTION_TIMEOUT", 10)
    options = {
        ldap.OPT_NETWORK_TIMEOUT: timeout,
        ldap.OPT_TIMEOUT: timeout,
        ldap.OPT_REFERRALS: 0,
    }

    ca_cert_file = env("LDAP_CA_CERT_FILE", "")
    if ca_cert_file:
        options[ldap.OPT_X_TLS_CACERTFILE] = ca_cert_file

    verify = env_bool("LDAP_TLS_VERIFY", True)
    if not verify:
        options[ldap.OPT_X_TLS_REQUIRE_CERT] = ldap.OPT_X_TLS_NEVER

    if ca_cert_file or not verify:
        # Without a fresh TLS context the options above apply to connections
        # created later rather than to this one.
        options[ldap.OPT_X_TLS_NEWCTX] = 0

    return options


_SETTINGS = ldap_settings()
globals().update(_SETTINGS)
__all__ = list(_SETTINGS)
