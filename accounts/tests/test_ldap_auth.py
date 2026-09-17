"""Signing in against a directory, end to end.

The real django-auth-ldap backend runs here -- service bind, user search, user
bind, group lookup, group mirroring -- against the in-memory directory in
ldap_fake.py. No server, no network.
"""

import os
from contextlib import contextmanager
from unittest.mock import patch

import ldap
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings

from config.auth_ldap import ldap_settings

from .ldap_fake import (
    ALICE_DN,
    BASE_DN,
    SERVICE_DN,
    SERVICE_PASSWORD,
    sample_directory,
)

User = get_user_model()

# django-auth-ldap caches the user search and group membership for an hour by
# default. Tests that change the directory mid-test need to see the change.
BASE_ENV = {
    "LDAP_SERVER_URI": "ldaps://ldap.jumpcloud.com:636",
    "LDAP_BIND_DN": SERVICE_DN,
    "LDAP_BIND_PASSWORD": SERVICE_PASSWORD,
    "LDAP_USER_SEARCH_BASE": BASE_DN,
    "LDAP_GROUP_SEARCH_BASE": BASE_DN,
    "LDAP_CACHE_TIMEOUT": "0",
}


class LDAPLoginTestCase(TestCase):
    """Base class: a fake directory in place of python-ldap's `initialize`."""

    def setUp(self):
        super().setUp()
        self.directory = sample_directory()
        patcher = patch.object(ldap, "initialize", self.directory.initialize)
        patcher.start()
        self.addCleanup(patcher.stop)
        cache.clear()
        self.addCleanup(cache.clear)

    @contextmanager
    def ldap_enabled(self, **env):
        """Apply an LDAP environment as settings, with LDAP login switched on."""
        with patch.dict(os.environ, {**BASE_ENV, **env}, clear=True):
            settings = ldap_settings()
        with override_settings(
            AUTH_ENABLE_LDAP=True,
            AUTHENTICATION_BACKENDS=[
                "django_auth_ldap.backend.LDAPBackend",
                "django.contrib.auth.backends.ModelBackend",
            ],
            **settings,
        ):
            yield

    def group_searches(self):
        return [
            filterstr
            for connection in self.directory.connections
            for _, _, filterstr in connection.searches
            if "groupOfNames" in filterstr
        ]


class CredentialTests(LDAPLoginTestCase):
    def test_valid_credentials_create_a_django_user(self):
        with self.ldap_enabled():
            user = authenticate(username="alice", password="alice-password")

        self.assertIsNotNone(user)
        self.assertEqual(user.username, "alice")
        self.assertTrue(User.objects.filter(username="alice").exists())

    def test_attributes_are_mapped_onto_the_user(self):
        with self.ldap_enabled():
            user = authenticate(username="alice", password="alice-password")

        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(user.last_name, "Alvarez")
        self.assertEqual(user.email, "alice@example.com")

    def test_attributes_are_refreshed_on_the_next_login(self):
        with self.ldap_enabled():
            authenticate(username="alice", password="alice-password")
            self.directory.entries[ALICE_DN.lower()]["mail"] = ["alice@example.org"]
            user = authenticate(username="alice", password="alice-password")

        self.assertEqual(user.email, "alice@example.org")

    def test_wrong_password_is_rejected(self):
        with self.ldap_enabled():
            user = authenticate(username="alice", password="not-her-password")

        self.assertIsNone(user)
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_unknown_user_is_rejected(self):
        with self.ldap_enabled():
            self.assertIsNone(authenticate(username="nobody", password="whatever"))

    def test_empty_password_is_rejected(self):
        """It must not fall through to an anonymous bind."""
        with self.ldap_enabled():
            self.assertIsNone(authenticate(username="alice", password=""))

    def test_the_service_account_binds_before_the_user_search(self):
        with self.ldap_enabled():
            authenticate(username="alice", password="alice-password")

        binds = [dn for c in self.directory.connections for dn in c.binds]
        self.assertEqual(binds[0], SERVICE_DN.lower())
        self.assertIn(ALICE_DN.lower(), binds)

    def test_a_bad_service_password_fails_the_login(self):
        # The reason goes to the logger, which is why settings configure it.
        with (
            self.ldap_enabled(LDAP_BIND_PASSWORD="wrong"),
            self.assertLogs("django_auth_ldap", "WARNING") as logged,
        ):
            self.assertIsNone(authenticate(username="alice", password="alice-password"))

        self.assertIn("INVALID_CREDENTIALS", "".join(logged.output))

    def test_an_unreachable_directory_fails_the_login_without_raising(self):
        def refuse(*args, **kwargs):
            raise ldap.SERVER_DOWN({"desc": "Can't contact LDAP server"})

        # django-auth-ldap swallows LDAPError and declines, so an unreachable
        # directory is a failed sign-in, not a 500.
        with (
            patch.object(ldap, "initialize", refuse),
            self.ldap_enabled(),
            self.assertLogs("django_auth_ldap", "WARNING") as logged,
        ):
            self.assertIsNone(authenticate(username="alice", password="alice-password"))

        self.assertIn("SERVER_DOWN", "".join(logged.output))


class TransportTests(LDAPLoginTestCase):
    def test_start_tls_is_requested_when_enabled(self):
        with self.ldap_enabled(
            LDAP_SERVER_URI="ldap://ldap.jumpcloud.com:389", LDAP_START_TLS="true"
        ):
            authenticate(username="alice", password="alice-password")

        self.assertTrue(any(c.start_tls_called for c in self.directory.connections))

    def test_start_tls_is_not_requested_by_default(self):
        with self.ldap_enabled():
            authenticate(username="alice", password="alice-password")

        self.assertFalse(any(c.start_tls_called for c in self.directory.connections))


class GroupMappingTests(LDAPLoginTestCase):
    def test_ldap_groups_are_mirrored_into_django_groups(self):
        with self.ldap_enabled():
            user = authenticate(username="alice", password="alice-password")

        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {"app-users", "engineering", "django-admins"},
        )

    def test_mirroring_removes_groups_the_user_has_left(self):
        with self.ldap_enabled():
            user = authenticate(username="alice", password="alice-password")
            self.assertIn("engineering", user.groups.values_list("name", flat=True))

            self.directory.entries[f"cn=engineering,{BASE_DN}".lower()]["member"] = []
            user = authenticate(username="alice", password="alice-password")

        self.assertNotIn("engineering", user.groups.values_list("name", flat=True))

    def test_mirroring_a_subset_leaves_other_groups_alone(self):
        local_group = Group.objects.create(name="locally-managed")

        with self.ldap_enabled(LDAP_MIRROR_GROUPS_ONLY="engineering,django-admins"):
            user = authenticate(username="alice", password="alice-password")
            user.groups.add(local_group)
            user = authenticate(username="alice", password="alice-password")

        names = set(user.groups.values_list("name", flat=True))
        self.assertIn("locally-managed", names)
        # app-users is a directory group, but outside the mirrored subset.
        self.assertNotIn("app-users", names)
        self.assertTrue({"engineering", "django-admins"} <= names)

    def test_mirroring_can_be_switched_off(self):
        with self.ldap_enabled(LDAP_MIRROR_GROUPS="false"):
            user = authenticate(username="alice", password="alice-password")

        self.assertEqual(user.groups.count(), 0)

    def test_no_group_base_means_no_group_lookup(self):
        with self.ldap_enabled(LDAP_GROUP_SEARCH_BASE=""):
            user = authenticate(username="alice", password="alice-password")

        self.assertIsNotNone(user)
        self.assertEqual(user.groups.count(), 0)
        self.assertEqual(self.group_searches(), [])

    def test_group_membership_is_cached_between_logins(self):
        with self.ldap_enabled(LDAP_CACHE_TIMEOUT="3600"):
            authenticate(username="alice", password="alice-password")
            after_first = len(self.group_searches())
            self.assertGreater(after_first, 0)

            authenticate(username="alice", password="alice-password")

            self.assertEqual(len(self.group_searches()), after_first)


class AccessRuleTests(LDAPLoginTestCase):
    def test_staff_and_superuser_flags_follow_group_membership(self):
        with self.ldap_enabled(
            LDAP_STAFF_GROUP=f"cn=django-admins,{BASE_DN}",
            LDAP_SUPERUSER_GROUP=f"cn=django-admins,{BASE_DN}",
        ):
            alice = authenticate(username="alice", password="alice-password")
            bob = authenticate(username="bob", password="bob-password")

        self.assertTrue(alice.is_staff)
        self.assertTrue(alice.is_superuser)
        self.assertFalse(bob.is_staff)
        self.assertFalse(bob.is_superuser)

    def test_flags_are_revoked_when_the_user_leaves_the_group(self):
        with self.ldap_enabled(LDAP_STAFF_GROUP=f"cn=django-admins,{BASE_DN}"):
            alice = authenticate(username="alice", password="alice-password")
            self.assertTrue(alice.is_staff)

            self.directory.entries[f"cn=django-admins,{BASE_DN}".lower()]["member"] = []
            alice = authenticate(username="alice", password="alice-password")

        self.assertFalse(alice.is_staff)

    def test_require_group_keeps_non_members_out(self):
        with self.ldap_enabled(LDAP_REQUIRE_GROUP=f"cn=app-users,{BASE_DN}"):
            self.assertIsNotNone(
                authenticate(username="alice", password="alice-password")
            )
            # carol authenticates against the directory but is in no group.
            self.assertIsNone(authenticate(username="carol", password="carol-password"))

    def test_deny_group_keeps_members_out(self):
        with self.ldap_enabled(LDAP_DENY_GROUP=f"cn=suspended,{BASE_DN}"):
            self.assertIsNotNone(
                authenticate(username="alice", password="alice-password")
            )
            self.assertIsNone(authenticate(username="bob", password="bob-password"))


class CoexistenceTests(LDAPLoginTestCase):
    def test_local_passwords_still_work_alongside_ldap(self):
        User.objects.create_user(username="localadmin", password="local-password")

        with self.ldap_enabled():
            user = authenticate(username="localadmin", password="local-password")

        self.assertIsNotNone(user)
        self.assertEqual(user.backend, "django.contrib.auth.backends.ModelBackend")

    def test_the_ldap_backend_is_absent_when_the_toggle_is_off(self):
        """config/settings.py leaves LDAPBackend out unless AUTH_ENABLE_LDAP."""
        from django.conf import settings

        if not settings.AUTH_ENABLE_LDAP:
            self.assertNotIn(
                "django_auth_ldap.backend.LDAPBackend",
                settings.AUTHENTICATION_BACKENDS,
            )
