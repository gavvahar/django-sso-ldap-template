"""The auth backend, URLs and login redirect are wired up as expected."""

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from config.oidc import endpoints_from_issuer

OIDC_TEST_SETTINGS = {
    "OIDC_RP_CLIENT_ID": "test-client-id",
    "OIDC_RP_CLIENT_SECRET": "test-client-secret",
    "OIDC_OP_AUTHORIZATION_ENDPOINT": "https://sso.example.com/application/o/authorize/",
    "OIDC_OP_TOKEN_ENDPOINT": "https://sso.example.com/application/o/token/",
    "OIDC_OP_USER_ENDPOINT": "https://sso.example.com/application/o/userinfo/",
    "OIDC_OP_JWKS_ENDPOINT": "https://sso.example.com/application/o/demo/jwks/",
    "OIDC_OP_LOGOUT_ENDPOINT": "https://sso.example.com/application/o/demo/end-session/",
}


class BackendWiringTests(TestCase):
    def test_oidc_backend_is_the_first_authentication_backend(self):
        self.assertEqual(
            settings.AUTHENTICATION_BACKENDS[0], "accounts.auth.OIDCBackend"
        )

    def test_backend_can_be_instantiated_with_configured_endpoints(self):
        from django.contrib.auth import get_backends

        with override_settings(**OIDC_TEST_SETTINGS):
            backends = [type(backend).__name__ for backend in get_backends()]
        self.assertIn("OIDCBackend", backends)

    def test_login_url_points_at_the_oidc_flow(self):
        self.assertEqual(reverse(settings.LOGIN_URL), "/oidc/authenticate/")

    def test_callback_url_is_registered(self):
        self.assertEqual(reverse("oidc_authentication_callback"), "/oidc/callback/")


@override_settings(**OIDC_TEST_SETTINGS)
class LoginFlowTests(TestCase):
    def test_login_redirects_to_the_provider_with_the_expected_parameters(self):
        response = self.client.get(reverse("oidc_authentication_init"))

        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertTrue(
            location.startswith(OIDC_TEST_SETTINGS["OIDC_OP_AUTHORIZATION_ENDPOINT"]),
            location,
        )
        self.assertIn("client_id=test-client-id", location)
        self.assertIn("response_type=code", location)
        self.assertIn("scope=openid", location)
        self.assertIn("code_challenge=", location)  # PKCE is on by default

    def test_protected_view_redirects_anonymous_users_into_the_flow(self):
        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers["Location"].startswith("/oidc/authenticate/"),
            response.headers["Location"],
        )

    def test_home_page_is_public(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log in with SSO")


class EndpointDerivationTests(TestCase):
    def test_authentik_endpoints_are_derived_from_the_issuer(self):
        endpoints = endpoints_from_issuer(
            "https://sso.example.com/application/o/my-app/"
        )

        self.assertEqual(
            endpoints["authorization_endpoint"],
            "https://sso.example.com/application/o/authorize/",
        )
        self.assertEqual(
            endpoints["token_endpoint"],
            "https://sso.example.com/application/o/token/",
        )
        self.assertEqual(
            endpoints["userinfo_endpoint"],
            "https://sso.example.com/application/o/userinfo/",
        )
        self.assertEqual(
            endpoints["jwks_uri"],
            "https://sso.example.com/application/o/my-app/jwks/",
        )
        self.assertEqual(
            endpoints["end_session_endpoint"],
            "https://sso.example.com/application/o/my-app/end-session/",
        )

    def test_issuer_without_trailing_slash_is_handled(self):
        with_slash = endpoints_from_issuer("https://sso.example.com/application/o/app/")
        without = endpoints_from_issuer("https://sso.example.com/application/o/app")

        self.assertEqual(with_slash, without)

    def test_no_issuer_yields_empty_endpoints(self):
        self.assertEqual(
            endpoints_from_issuer(""),
            {
                "authorization_endpoint": "",
                "token_endpoint": "",
                "userinfo_endpoint": "",
                "jwks_uri": "",
                "end_session_endpoint": "",
            },
        )


class BackendCompositionTests(TestCase):
    """Login methods are switched on independently via AUTH_ENABLE_* toggles."""

    def test_both_backends_are_enabled_by_default(self):
        self.assertEqual(
            settings.AUTHENTICATION_BACKENDS,
            [
                "accounts.auth.OIDCBackend",
                "django.contrib.auth.backends.ModelBackend",
            ],
        )

    @override_settings(AUTH_ENABLE_OIDC=False, TESTING=False)
    def test_configuration_checks_stand_down_when_sso_is_off(self):
        from accounts.checks import check_oidc_configuration

        self.assertEqual(check_oidc_configuration(None), [])

    @override_settings(AUTH_ENABLE_OIDC=True, TESTING=False)
    def test_configuration_checks_run_when_sso_is_on(self):
        from accounts.checks import check_oidc_configuration

        # Nothing is configured in the test environment, so every required
        # setting should be reported.
        self.assertTrue(check_oidc_configuration(None))
