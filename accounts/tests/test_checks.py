"""`manage.py check` explains what is missing before SSO can work."""

from django.test import SimpleTestCase, override_settings

from accounts.checks import oidc_configuration_problems

from .test_wiring import OIDC_TEST_SETTINGS


class ConfigurationCheckTests(SimpleTestCase):
    @override_settings(**OIDC_TEST_SETTINGS, OIDC_ISSUER="https://sso.example.com/application/o/demo/")
    def test_fully_configured_project_reports_no_problems(self):
        self.assertEqual(oidc_configuration_problems(), [])

    @override_settings(**{**OIDC_TEST_SETTINGS, "OIDC_RP_CLIENT_ID": ""})
    def test_missing_client_id_is_an_error(self):
        problems = oidc_configuration_problems()

        self.assertEqual([problem.id for problem in problems], ["accounts.E001"])
        self.assertIn("OIDC_RP_CLIENT_ID", problems[0].msg)

    @override_settings(**OIDC_TEST_SETTINGS, OIDC_RP_SCOPES="email profile")
    def test_scopes_without_openid_are_an_error(self):
        problems = oidc_configuration_problems()

        self.assertEqual([problem.id for problem in problems], ["accounts.E002"])

    @override_settings(**OIDC_TEST_SETTINGS, OIDC_ISSUER="http://sso.example.com/application/o/demo/")
    def test_plain_http_issuer_is_a_warning(self):
        problems = oidc_configuration_problems()

        self.assertEqual([problem.id for problem in problems], ["accounts.W001"])
