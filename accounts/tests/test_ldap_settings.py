"""config/auth_ldap.py turns environment variables into AUTH_LDAP_* settings."""

import os
from unittest.mock import patch

import ldap
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django_auth_ldap import config as ldap_config

from config.auth_ldap import DEFAULT_USER_SEARCH_FILTER, GROUP_TYPES, ldap_settings

from .ldap_fake import BASE_DN

MINIMAL = {
    "LDAP_SERVER_URI": "ldaps://ldap.jumpcloud.com:636",
    "LDAP_USER_SEARCH_BASE": BASE_DN,
}


def settings_for(**env):
    """Build the settings dict from an environment, ignoring the real one."""
    with patch.dict(os.environ, {**MINIMAL, **env}, clear=True):
        return ldap_settings()


class ConnectionSettingsTests(SimpleTestCase):
    def test_minimal_configuration_produces_a_usable_user_search(self):
        settings = settings_for()

        self.assertEqual(
            settings["AUTH_LDAP_SERVER_URI"], "ldaps://ldap.jumpcloud.com:636"
        )
        search = settings["AUTH_LDAP_USER_SEARCH"]
        self.assertEqual(search.base_dn, BASE_DN)
        self.assertEqual(search.scope, ldap.SCOPE_SUBTREE)
        self.assertEqual(search.filterstr, DEFAULT_USER_SEARCH_FILTER)

    def test_an_empty_bind_dn_means_an_anonymous_bind(self):
        settings = settings_for()

        self.assertEqual(settings["AUTH_LDAP_BIND_DN"], "")
        self.assertEqual(settings["AUTH_LDAP_BIND_PASSWORD"], "")

    def test_the_bind_password_is_not_stripped(self):
        """Passwords can legitimately start or end with whitespace."""
        settings = settings_for(LDAP_BIND_PASSWORD="  spaced  ")

        self.assertEqual(settings["AUTH_LDAP_BIND_PASSWORD"], "  spaced  ")

    def test_missing_settings_are_left_blank_for_manage_py_check(self):
        """Importing must not explode on a checkout with no .env; the check
        rules in accounts/ldap_checks.py report what is missing instead."""
        with patch.dict(os.environ, {}, clear=True):
            settings = ldap_settings()

        self.assertEqual(settings["AUTH_LDAP_SERVER_URI"], "")
        self.assertEqual(settings["AUTH_LDAP_USER_SEARCH"].base_dn, "")

    def test_start_tls_is_off_by_default(self):
        self.assertIs(settings_for()["AUTH_LDAP_START_TLS"], False)

    def test_start_tls_can_be_switched_on(self):
        self.assertIs(settings_for(LDAP_START_TLS="true")["AUTH_LDAP_START_TLS"], True)


class UserLookupSettingsTests(SimpleTestCase):
    def test_the_user_filter_can_be_overridden(self):
        settings = settings_for(LDAP_USER_SEARCH_FILTER="(sAMAccountName=%(user)s)")

        self.assertEqual(
            settings["AUTH_LDAP_USER_SEARCH"].filterstr, "(sAMAccountName=%(user)s)"
        )

    def test_search_scope_is_configurable(self):
        for name, scope in (
            ("base", ldap.SCOPE_BASE),
            ("onelevel", ldap.SCOPE_ONELEVEL),
            ("subtree", ldap.SCOPE_SUBTREE),
        ):
            with self.subTest(scope=name):
                settings = settings_for(LDAP_USER_SEARCH_SCOPE=name)
                self.assertEqual(settings["AUTH_LDAP_USER_SEARCH"].scope, scope)

    def test_an_unknown_scope_is_a_configuration_error(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "LDAP_USER_SEARCH_SCOPE"
        ):
            settings_for(LDAP_USER_SEARCH_SCOPE="sideways")

    def test_attributes_map_to_django_user_fields_by_default(self):
        self.assertEqual(
            settings_for()["AUTH_LDAP_USER_ATTR_MAP"],
            {"first_name": "givenName", "last_name": "sn", "email": "mail"},
        )

    def test_the_attribute_map_can_be_replaced(self):
        settings = settings_for(
            LDAP_USER_ATTR_MAP="email=userPrincipalName, first_name=cn"
        )

        self.assertEqual(
            settings["AUTH_LDAP_USER_ATTR_MAP"],
            {"email": "userPrincipalName", "first_name": "cn"},
        )

    def test_a_malformed_attribute_map_is_a_configuration_error(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "LDAP_USER_ATTR_MAP"):
            settings_for(LDAP_USER_ATTR_MAP="first_name")


class GroupSettingsTests(SimpleTestCase):
    def test_no_group_base_means_no_group_settings(self):
        settings = settings_for()

        self.assertNotIn("AUTH_LDAP_GROUP_SEARCH", settings)
        self.assertNotIn("AUTH_LDAP_GROUP_TYPE", settings)

    def test_groups_default_to_group_of_names(self):
        settings = settings_for(LDAP_GROUP_SEARCH_BASE=BASE_DN)

        self.assertIsInstance(
            settings["AUTH_LDAP_GROUP_TYPE"], ldap_config.GroupOfNamesType
        )
        self.assertEqual(
            settings["AUTH_LDAP_GROUP_SEARCH"].filterstr, "(objectClass=groupOfNames)"
        )
        self.assertIs(settings["AUTH_LDAP_MIRROR_GROUPS"], True)

    def test_every_documented_group_type_builds(self):
        for type_name, (class_name, object_class) in GROUP_TYPES.items():
            with self.subTest(group_type=type_name):
                settings = settings_for(
                    LDAP_GROUP_SEARCH_BASE=BASE_DN, LDAP_GROUP_TYPE=type_name
                )

                self.assertEqual(
                    type(settings["AUTH_LDAP_GROUP_TYPE"]).__name__, class_name
                )
                self.assertEqual(
                    settings["AUTH_LDAP_GROUP_SEARCH"].filterstr,
                    f"(objectClass={object_class})",
                )

    def test_an_unknown_group_type_is_a_configuration_error(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "LDAP_GROUP_TYPE"):
            settings_for(
                LDAP_GROUP_SEARCH_BASE=BASE_DN, LDAP_GROUP_TYPE="groupOfThings"
            )

    def test_the_group_filter_can_be_overridden(self):
        settings = settings_for(
            LDAP_GROUP_SEARCH_BASE=BASE_DN,
            LDAP_GROUP_SEARCH_FILTER="(&(objectClass=groupOfNames)(cn=django-*))",
        )

        self.assertEqual(
            settings["AUTH_LDAP_GROUP_SEARCH"].filterstr,
            "(&(objectClass=groupOfNames)(cn=django-*))",
        )

    def test_mirroring_a_subset_of_groups(self):
        settings = settings_for(
            LDAP_GROUP_SEARCH_BASE=BASE_DN,
            LDAP_MIRROR_GROUPS_ONLY="engineering, support",
        )

        self.assertEqual(
            settings["AUTH_LDAP_MIRROR_GROUPS"], ["engineering", "support"]
        )

    def test_mirroring_can_be_switched_off(self):
        settings = settings_for(
            LDAP_GROUP_SEARCH_BASE=BASE_DN, LDAP_MIRROR_GROUPS="false"
        )

        self.assertIs(settings["AUTH_LDAP_MIRROR_GROUPS"], False)

    def test_require_and_deny_groups_are_passed_through(self):
        settings = settings_for(
            LDAP_GROUP_SEARCH_BASE=BASE_DN,
            LDAP_REQUIRE_GROUP=f"cn=app-users,{BASE_DN}",
            LDAP_DENY_GROUP=f"cn=suspended,{BASE_DN}",
        )

        self.assertEqual(
            settings["AUTH_LDAP_REQUIRE_GROUP"], f"cn=app-users,{BASE_DN}"
        )
        self.assertEqual(settings["AUTH_LDAP_DENY_GROUP"], f"cn=suspended,{BASE_DN}")

    def test_staff_and_superuser_groups_become_user_flags(self):
        settings = settings_for(
            LDAP_GROUP_SEARCH_BASE=BASE_DN,
            LDAP_STAFF_GROUP=f"cn=staff,{BASE_DN}",
            LDAP_SUPERUSER_GROUP=f"cn=admins,{BASE_DN}",
        )

        self.assertEqual(
            settings["AUTH_LDAP_USER_FLAGS_BY_GROUP"],
            {
                "is_staff": f"cn=staff,{BASE_DN}",
                "is_superuser": f"cn=admins,{BASE_DN}",
            },
        )

    def test_a_group_rule_without_a_group_base_is_a_configuration_error(self):
        """A LDAP_STAFF_GROUP that silently grants nobody staff is worse than
        an error at startup."""
        for variable in (
            "LDAP_REQUIRE_GROUP",
            "LDAP_DENY_GROUP",
            "LDAP_STAFF_GROUP",
            "LDAP_SUPERUSER_GROUP",
        ):
            with self.subTest(variable=variable), self.assertRaisesMessage(
                ImproperlyConfigured, "LDAP_GROUP_SEARCH_BASE"
            ):
                settings_for(**{variable: f"cn=admins,{BASE_DN}"})

    def test_group_permissions_are_off_by_default(self):
        settings = settings_for(LDAP_GROUP_SEARCH_BASE=BASE_DN)

        self.assertIs(settings["AUTH_LDAP_FIND_GROUP_PERMS"], False)


class TransportSettingsTests(SimpleTestCase):
    def test_connection_timeouts_and_referrals_have_defaults(self):
        options = settings_for()["AUTH_LDAP_CONNECTION_OPTIONS"]

        self.assertEqual(options[ldap.OPT_NETWORK_TIMEOUT], 10)
        self.assertEqual(options[ldap.OPT_TIMEOUT], 10)
        self.assertEqual(options[ldap.OPT_REFERRALS], 0)

    def test_the_timeout_is_configurable(self):
        options = settings_for(LDAP_CONNECTION_TIMEOUT="3")[
            "AUTH_LDAP_CONNECTION_OPTIONS"
        ]

        self.assertEqual(options[ldap.OPT_NETWORK_TIMEOUT], 3)

    def test_a_non_numeric_timeout_is_a_configuration_error(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "LDAP_CONNECTION_TIMEOUT"):
            settings_for(LDAP_CONNECTION_TIMEOUT="soon")

    def test_certificates_are_verified_unless_told_otherwise(self):
        options = settings_for()["AUTH_LDAP_CONNECTION_OPTIONS"]

        self.assertNotIn(ldap.OPT_X_TLS_REQUIRE_CERT, options)

    def test_verification_can_be_turned_off_for_a_lab_directory(self):
        options = settings_for(LDAP_TLS_VERIFY="false")[
            "AUTH_LDAP_CONNECTION_OPTIONS"
        ]

        self.assertEqual(options[ldap.OPT_X_TLS_REQUIRE_CERT], ldap.OPT_X_TLS_NEVER)
        # Without a fresh TLS context the option would not apply to this
        # connection.
        self.assertEqual(options[ldap.OPT_X_TLS_NEWCTX], 0)

    def test_a_private_ca_bundle_is_passed_through(self):
        options = settings_for(LDAP_CA_CERT_FILE="/etc/ssl/corp.pem")[
            "AUTH_LDAP_CONNECTION_OPTIONS"
        ]

        self.assertEqual(options[ldap.OPT_X_TLS_CACERTFILE], "/etc/ssl/corp.pem")
        self.assertEqual(options[ldap.OPT_X_TLS_NEWCTX], 0)


class CacheSettingsTests(SimpleTestCase):
    def test_group_membership_is_cached_for_an_hour_by_default(self):
        self.assertEqual(settings_for()["AUTH_LDAP_CACHE_TIMEOUT"], 3600)

    def test_caching_can_be_switched_off(self):
        self.assertEqual(
            settings_for(LDAP_CACHE_TIMEOUT="0")["AUTH_LDAP_CACHE_TIMEOUT"], 0
        )
