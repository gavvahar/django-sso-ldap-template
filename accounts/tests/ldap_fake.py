"""An in-memory stand-in for a directory server.

django-auth-ldap talks to python-ldap through a small surface: it calls
``ldap.initialize()``, then ``set_option``, ``start_tls_s``, ``simple_bind_s``
and ``search_s`` on the object that comes back. :class:`FakeDirectory` answers
those four, so the whole login path (bind, user lookup, group lookup, group
mirroring) runs in the test suite with no server anywhere.

Entries are plain dicts of ``str -> list[str]``; the fake encodes them to bytes
on the way out because that is what python-ldap returns.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import ldap


class FakeDirectory:
    """A tiny directory: DNs with attributes, plus passwords that bind."""

    def __init__(
        self,
        entries: dict[str, dict[str, list[str]]],
        passwords: dict[str, str] | None = None,
    ) -> None:
        # DNs are matched case-insensitively, as a real directory does.
        self.entries = {dn.lower(): attrs for dn, attrs in entries.items()}
        self.passwords = {
            dn.lower(): password for dn, password in (passwords or {}).items()
        }
        self.connections: list[FakeConnection] = []

    def initialize(self, uri: str, *args: Any, **kwargs: Any) -> FakeConnection:
        connection = FakeConnection(self, uri)
        self.connections.append(connection)
        return connection

    def check_password(self, dn: str, password: str) -> bool:
        return self.passwords.get(dn.lower()) == password

    def search(
        self, base_dn: str, scope: int, filterstr: str
    ) -> list[tuple[str, dict]]:
        criteria = parse_filter(filterstr)
        return [
            (dn, _encode(attrs))
            for dn, attrs in self.entries.items()
            if _in_scope(dn, base_dn, scope) and criteria(dn, attrs)
        ]


class FakeConnection:
    """The subset of python-ldap's LDAPObject that django-auth-ldap uses."""

    def __init__(self, directory: FakeDirectory, uri: str) -> None:
        self.directory = directory
        self.uri = uri
        self.options: dict[int, Any] = {}
        self.start_tls_called = False
        self.bound_as: str | None = None
        self.binds: list[str] = []
        self.searches: list[tuple[str, int, str]] = []

    def set_option(self, option: int, value: Any) -> None:
        self.options[option] = value

    def start_tls_s(self) -> None:
        self.start_tls_called = True

    def simple_bind_s(self, dn: str = "", password: str = "") -> tuple:
        if dn == "":
            # Anonymous bind. A real server may refuse it; this one allows it
            # so the anonymous-lookup configuration is testable.
            self.bound_as = None
            self.binds.append("")
            return (97, [], 1, [])

        if not self.directory.check_password(dn, password):
            raise ldap.INVALID_CREDENTIALS(
                {"desc": "Invalid credentials", "info": f"bind failed for {dn}"}
            )

        self.bound_as = dn.lower()
        self.binds.append(dn.lower())
        return (97, [], 1, [])

    def search_s(
        self,
        base_dn: str,
        scope: int,
        filterstr: str = "(objectClass=*)",
        attrlist=None,
    ) -> list[tuple[str, dict]]:
        self.searches.append((base_dn, scope, filterstr))
        results = self.directory.search(base_dn, scope, filterstr)
        if attrlist is None:
            return results
        wanted = {name.lower() for name in attrlist}
        return [
            (dn, {k: v for k, v in attrs.items() if k.lower() in wanted})
            for dn, attrs in results
        ]

    def compare_s(self, dn: str, attr: str, value: bytes) -> int:
        """Membership check used by the group types for require/deny groups."""
        entry = self.directory.entries.get(dn.lower())
        if entry is None:
            raise ldap.NO_SUCH_OBJECT({"desc": "No such object", "info": dn})
        wanted = value.decode("utf-8").lower()
        return int(any(v.lower() == wanted for v in _values(entry, attr)))

    def unbind_s(self) -> None:
        self.bound_as = None


def _encode(attrs: dict[str, list[str]]) -> dict[str, list[bytes]]:
    return {
        name: [value.encode("utf-8") for value in values]
        for name, values in attrs.items()
    }


def _in_scope(dn: str, base_dn: str, scope: int) -> bool:
    dn, base_dn = dn.lower(), base_dn.lower()
    if scope == ldap.SCOPE_BASE:
        return dn == base_dn
    if scope == ldap.SCOPE_ONELEVEL:
        return dn.endswith("," + base_dn) and "," not in dn[: -len(base_dn) - 1]
    return dn == base_dn or dn.endswith("," + base_dn)


# --- RFC 4515 filter matching -------------------------------------------------
#
# Enough of the grammar for what django-auth-ldap emits: and, or, not, equality
# and presence. Values are compared case-insensitively, matching the
# caseIgnoreMatch rule that uid, cn, mail and member all use in practice.

_ESCAPE_RE = re.compile(r"\\([0-9a-fA-F]{2})")


def parse_filter(filterstr: str):
    """Compile an LDAP filter into a ``(dn, attrs) -> bool`` predicate."""
    predicate, rest = _parse(filterstr.strip(), 0)
    if rest != len(filterstr.strip()):
        raise ValueError(f"trailing junk in LDAP filter: {filterstr!r}")
    return predicate


def _parse(text: str, i: int):
    if i >= len(text) or text[i] != "(":
        raise ValueError(f"expected '(' at {i} in {text!r}")
    i += 1

    if text[i] == "&":
        parts, i = _parse_list(text, i + 1)
        return (lambda dn, attrs: all(p(dn, attrs) for p in parts)), _close(text, i)
    if text[i] == "|":
        parts, i = _parse_list(text, i + 1)
        return (lambda dn, attrs: any(p(dn, attrs) for p in parts)), _close(text, i)
    if text[i] == "!":
        inner, i = _parse(text, i + 1)
        return (lambda dn, attrs: not inner(dn, attrs)), _close(text, i)

    end = text.index(")", i)
    item = text[i:end]
    if "=" not in item:
        raise ValueError(f"unsupported filter item {item!r}")
    attr, _, value = item.partition("=")
    return _item_predicate(attr.strip(), _unescape(value)), end + 1


def _parse_list(text: str, i: int):
    parts = []
    while i < len(text) and text[i] == "(":
        part, i = _parse(text, i)
        parts.append(part)
    return parts, i


def _close(text: str, i: int) -> int:
    if i >= len(text) or text[i] != ")":
        raise ValueError(f"expected ')' at {i} in {text!r}")
    return i + 1


def _unescape(value: str) -> str:
    return _ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), value)


def _item_predicate(attr: str, value: str):
    def predicate(dn: str, attrs: dict[str, list[str]]) -> bool:
        present = _values(attrs, attr)
        if value == "*":
            return bool(present)
        return any(v.lower() == value.lower() for v in present)

    return predicate


def _values(attrs: dict[str, list[str]], attr: str) -> Iterable[str]:
    for name, values in attrs.items():
        if name.lower() == attr.lower():
            return values
    return []


# --- a sample directory -------------------------------------------------------
#
# Shaped like JumpCloud's hosted LDAP: one flat ou=Users holding both people and
# groupOfNames groups, under an org-specific o= node. See docs/ldap.md.

ORG_ID = "o=5f0000000000000000000001"
BASE_DN = f"ou=Users,{ORG_ID},dc=jumpcloud,dc=com"

SERVICE_DN = f"uid=ldapservice,{BASE_DN}"
SERVICE_PASSWORD = "service-secret"

ALICE_DN = f"uid=alice,{BASE_DN}"
BOB_DN = f"uid=bob,{BASE_DN}"
CAROL_DN = f"uid=carol,{BASE_DN}"


def person(uid, first, last):
    return {
        "objectClass": ["top", "person", "organizationalPerson", "inetOrgPerson"],
        "uid": [uid],
        "cn": [f"{first} {last}"],
        "givenName": [first],
        "sn": [last],
        "mail": [f"{uid}@example.com"],
    }


def group(name, members):
    return {
        "objectClass": ["top", "groupOfNames"],
        "cn": [name],
        "member": members,
    }


def sample_directory():
    """Three people and four groups.

    alice is in every group but ``suspended``; bob is in ``app-users`` and
    ``suspended``; carol is in none, which is what makes her useful for
    testing LDAP_REQUIRE_GROUP.
    """
    return FakeDirectory(
        entries={
            SERVICE_DN: person("ldapservice", "LDAP", "Service"),
            ALICE_DN: person("alice", "Alice", "Alvarez"),
            BOB_DN: person("bob", "Bob", "Brennan"),
            CAROL_DN: person("carol", "Carol", "Chen"),
            f"cn=app-users,{BASE_DN}": group("app-users", [ALICE_DN, BOB_DN]),
            f"cn=engineering,{BASE_DN}": group("engineering", [ALICE_DN]),
            f"cn=django-admins,{BASE_DN}": group("django-admins", [ALICE_DN]),
            f"cn=suspended,{BASE_DN}": group("suspended", [BOB_DN]),
        },
        passwords={
            SERVICE_DN: SERVICE_PASSWORD,
            ALICE_DN: "alice-password",
            BOB_DN: "bob-password",
            CAROL_DN: "carol-password",
        },
    )
