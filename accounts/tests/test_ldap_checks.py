"""`manage.py check` explains what is missing before LDAP login can work."""

import ldap
from django.test import SimpleTestCase, override_settings
from django_auth_ldap.config import GroupOfNamesType, LDAPSearch

from accounts.ldap_checks import ldap_configuration_problems

from .ldap_fake import BASE_DN

CONFIGURED = {
    "AUTH_ENABLE_LDAP": True,
    "AUTH_LDAP_SERVER_URI": "ldaps://ldap.jumpcloud.com:636",
    "AUTH_LDAP_BIND_DN": f"uid=ldapservice,{BASE_DN}",
    "AUTH_LDAP_BIND_PASSWORD": "service-secret",
    "AUTH_LDAP_START_TLS": False,
    "AUTH_LDAP_USER_SEARCH": LDAPSearch(BASE_DN, ldap.SCOPE_SUBTREE, "(uid=%(user)s)"),
}

WITH_GROUPS = {
    **CONFIGURED,
    "AUTH_LDAP_GROUP_SEARCH": LDAPSearch(
        BASE_DN, ldap.SCOPE_SUBTREE, "(objectClass=groupOfNames)"
    ),
    "AUTH_LDAP_GROUP_TYPE": GroupOfNamesType(name_attr="cn"),
}


def ids(problems):
    return [problem.id for problem in problems]


class LDAPConfigurationCheckTests(SimpleTestCase):
    @override_settings(**CONFIGURED)
    def test_a_configured_directory_reports_no_problems(self):
        self.assertEqual(ldap_configuration_problems(), [])

    @override_settings(**{**CONFIGURED, "AUTH_LDAP_SERVER_URI": ""})
    def test_a_missing_server_uri_is_an_error(self):
        problems = ldap_configuration_problems()

        self.assertEqual(ids(problems), ["accounts.E010"])
        self.assertIn("LDAP_SERVER_URI", problems[0].msg)

    @override_settings(
        **{
            **CONFIGURED,
            "AUTH_LDAP_USER_SEARCH": LDAPSearch("", ldap.SCOPE_SUBTREE, "(uid=%(user)s)"),
        }
    )
    def test_a_missing_user_search_base_is_an_error(self):
        problems = ldap_configuration_problems()

        self.assertEqual(ids(problems), ["accounts.E011"])
        self.assertIn("LDAP_USER_SEARCH_BASE", problems[0].msg)

    @override_settings(
        **{
            **CONFIGURED,
            "AUTH_LDAP_SERVER_URI": "ldap://ldap.example.com:389",
        }
    )
    def test_plain_ldap_without_start_tls_is_a_warning(self):
        problems = ldap_configuration_problems()

        self.assertEqual(ids(problems), ["accounts.W010"])

    @override_settings(
        **{
            **CONFIGURED,
            "AUTH_LDAP_SERVER_URI": "ldap://ldap.example.com:389",
            "AUTH_LDAP_START_TLS": True,
        }
    )
    def test_plain_ldap_with_start_tls_is_fine(self):
        self.assertEqual(ldap_configuration_problems(), [])

    @override_settings(**{**CONFIGURED, "AUTH_LDAP_BIND_PASSWORD": ""})
    def test_a_bind_dn_without_a_password_is_a_warning(self):
        problems = ldap_configuration_problems()

        self.assertEqual(ids(problems), ["accounts.W011"])


class GroupRuleCheckTests(SimpleTestCase):
    @override_settings(
        **{**WITH_GROUPS, "AUTH_LDAP_REQUIRE_GROUP": f"cn=app-users,{BASE_DN}"}
    )
    def test_a_group_rule_with_a_group_search_is_fine(self):
        self.assertEqual(ldap_configuration_problems(), [])

    @override_settings(**{**WITH_GROUPS, "AUTH_LDAP_REQUIRE_GROUP": "app-users"})
    def test_a_group_name_instead_of_a_dn_is_a_warning(self):
        """The commonest LDAP mistake: these settings match on the full DN."""
        problems = ldap_configuration_problems()

        self.assertEqual(ids(problems), ["accounts.W012"])
        self.assertIn("LDAP_REQUIRE_GROUP", problems[0].msg)

    @override_settings(
        **{**WITH_GROUPS, "AUTH_LDAP_USER_FLAGS_BY_GROUP": {"is_superuser": "admins"}}
    )
    def test_a_flag_group_name_instead_of_a_dn_is_a_warning(self):
        problems = ldap_configuration_problems()

        self.assertEqual(ids(problems), ["accounts.W012"])
        self.assertIn("LDAP_SUPERUSER_GROUP", problems[0].msg)
