"""Claims coming back from the provider map onto the Django user."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings

from accounts.auth import OIDCBackend, provider_logout_url

from .test_wiring import OIDC_TEST_SETTINGS

CLAIMS = {
    "sub": "6b2d1e1a",
    "preferred_username": "aduncan",
    "email": "aduncan@example.com",
    "given_name": "Avery",
    "family_name": "Duncan",
    "groups": ["engineering", "sso-admins"],
}

User = get_user_model()


@override_settings(**OIDC_TEST_SETTINGS)
class UserMappingTests(TestCase):
    def setUp(self):
        self.backend = OIDCBackend()

    def test_create_user_maps_username_name_and_email(self):
        user = self.backend.create_user(CLAIMS)

        self.assertEqual(user.username, "aduncan")
        self.assertEqual(user.email, "aduncan@example.com")
        self.assertEqual(user.get_full_name(), "Avery Duncan")
        self.assertFalse(user.has_usable_password())

    def test_create_user_syncs_groups_and_creates_missing_ones(self):
        user = self.backend.create_user(CLAIMS)

        self.assertCountEqual(
            user.groups.values_list("name", flat=True), ["engineering", "sso-admins"]
        )

    def test_update_user_removes_groups_the_provider_dropped(self):
        user = self.backend.create_user(CLAIMS)

        self.backend.update_user(user, {**CLAIMS, "groups": ["engineering"]})

        self.assertCountEqual(user.groups.values_list("name", flat=True), ["engineering"])

    def test_existing_user_is_matched_by_email_rather_than_duplicated(self):
        User.objects.create_user("old-name", email="ADuncan@example.com")

        matched = self.backend.filter_users_by_claims(CLAIMS)

        self.assertEqual([u.username for u in matched], ["old-name"])

    def test_single_name_claim_is_split_when_given_and_family_are_absent(self):
        user = self.backend.create_user(
            {"preferred_username": "bo", "email": "bo@example.com", "name": "Bo Nilsson"}
        )

        self.assertEqual(user.first_name, "Bo")
        self.assertEqual(user.last_name, "Nilsson")

    def test_username_falls_back_to_the_email_local_part(self):
        user = self.backend.create_user({"email": "noname@example.com"})

        self.assertEqual(user.username, "noname")

    @override_settings(
        **OIDC_TEST_SETTINGS, OIDC_STAFF_GROUP="sso-admins", OIDC_SUPERUSER_GROUP="root"
    )
    def test_staff_and_superuser_follow_group_membership(self):
        user = self.backend.create_user(CLAIMS)

        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)

        self.backend.update_user(user, {**CLAIMS, "groups": []})
        user.refresh_from_db()

        self.assertFalse(user.is_staff)

    @override_settings(**OIDC_TEST_SETTINGS, OIDC_SYNC_GROUPS=False)
    def test_group_sync_can_be_turned_off(self):
        user = self.backend.create_user(CLAIMS)

        self.assertEqual(user.groups.count(), 0)
        self.assertEqual(Group.objects.count(), 0)


@override_settings(**OIDC_TEST_SETTINGS)
class ProviderLogoutTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().post("/oidc/logout/")
        self.request.session = {}

    def test_logout_url_includes_the_id_token_hint(self):
        self.request.session["oidc_id_token"] = "a.b.c"

        url = provider_logout_url(self.request)

        self.assertTrue(
            url.startswith(OIDC_TEST_SETTINGS["OIDC_OP_LOGOUT_ENDPOINT"]), url
        )
        self.assertIn("id_token_hint=a.b.c", url)
        self.assertIn("post_logout_redirect_uri=http", url)

    def test_logout_url_falls_back_to_local_redirect_without_a_provider(self):
        with override_settings(OIDC_OP_LOGOUT_ENDPOINT=""):
            url = provider_logout_url(self.request)

        self.assertEqual(url, "http://testserver/")
