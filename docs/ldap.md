# LDAP login

The template can authenticate against an LDAP directory alongside its OIDC
single sign-on, using [django-auth-ldap][dal]. It is off until you set
`AUTH_ENABLE_LDAP=true`, and each login method is independent: SSO only, LDAP
only, both, or either plus local Django passwords.

With LDAP on, a sign-in goes: bind as the service account, find the person by
the username they typed, bind as them with the password they typed, and — if a
group base is configured — read their groups and copy them onto the Django
user.

[dal]: https://django-auth-ldap.readthedocs.io/

## Install

django-auth-ldap is not in `requirements.txt`, because its `python-ldap`
dependency is a C extension that needs OpenLDAP's headers to build. Installing
it is opt-in:

```bash
pip install -r requirements.txt -r requirements-ldap.txt
```

| Platform        | Headers needed first                                                                                                            |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Debian / Ubuntu | `sudo apt-get install libldap2-dev libsasl2-dev`                                                                                |
| RHEL / Fedora   | `sudo dnf install openldap-devel cyrus-sasl-devel`                                                                              |
| macOS           | `brew install openldap`, then `export LDFLAGS="-L$(brew --prefix openldap)/lib" CPPFLAGS="-I$(brew --prefix openldap)/include"` |

Install them in your Docker build stage and in CI too. The LDAP tests need the
package importable, because they exercise the real backend; they do not need a
directory.

## Turn it on

Set `AUTH_ENABLE_LDAP=true` and fill in the connection settings in `.env`. The
minimum is two values beyond the toggle:

```dotenv
AUTH_ENABLE_LDAP=true
LDAP_SERVER_URI=ldaps://ldap.example.com:636
LDAP_USER_SEARCH_BASE=ou=People,dc=example,dc=com
```

That searches anonymously. Almost every directory wants a service account:

```dotenv
LDAP_BIND_DN=uid=ldapservice,ou=People,dc=example,dc=com
LDAP_BIND_PASSWORD=...
```

Then `python manage.py check` will tell you if anything is still missing, the
same way it does for the OIDC settings.

`.env.example` lists every variable with its default. The ones worth knowing:

| Variable                                    | What it does                                                                                                                                                                                        |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LDAP_USER_SEARCH_FILTER`                   | How a typed username maps to a directory entry. `%(user)s` is substituted and escaped. Default `(&(objectClass=inetOrgPerson)(uid=%(user)s))`; on Active Directory use `(sAMAccountName=%(user)s)`. |
| `LDAP_USER_ATTR_MAP`                        | `django_field=ldapAttribute` pairs, comma separated.                                                                                                                                                |
| `LDAP_GROUP_SEARCH_BASE`                    | Where groups live. Leave blank and no group lookup happens at all.                                                                                                                                  |
| `LDAP_GROUP_TYPE`                           | The schema your groups use — the full list is in `.env.example`. `groupOfNames` covers JumpCloud, OpenLDAP and FreeIPA.                                                                             |
| `LDAP_MIRROR_GROUPS`                        | Copy directory groups onto the Django user at every login. Membership is then owned by the directory: a group someone has left is removed.                                                          |
| `LDAP_MIRROR_GROUPS_ONLY`                   | Mirror just these group names, leaving any other Django group membership managed locally.                                                                                                           |
| `LDAP_REQUIRE_GROUP` / `LDAP_DENY_GROUP`    | Full group DNs. Someone outside the required group, or inside the denied one, cannot sign in even with the right password.                                                                          |
| `LDAP_STAFF_GROUP` / `LDAP_SUPERUSER_GROUP` | Full group DNs granting `is_staff` / `is_superuser`. Re-evaluated at every login, so removing someone from the group removes the flag.                                                              |
| `LDAP_CACHE_TIMEOUT`                        | Seconds to cache the user lookup and group membership. An hour by default; set `0` while debugging a group rule.                                                                                    |

A variable you have not filled in yet is reported by `manage.py check`. A
variable filled in with something meaningless — an unknown `LDAP_GROUP_TYPE`, a
search scope that is not a scope — raises `ImproperlyConfigured` at startup
naming the variable, because there is no sensible value to carry forward.

## Point it at JumpCloud

JumpCloud exposes a hosted LDAP directory at `ldap.jumpcloud.com`. Three things
have to be true in the JumpCloud admin console first:

1. **The LDAP directory exists.** Under **Directories**, create the _LDAP
   Directory_ if your org does not have one, and note the organisation ID it
   shows — a 24-character hex string, also visible in the console URL.
   Everything below calls it `YOUR_ORG_ID`.
2. **Your users can reach it.** LDAP access is granted through user groups:
   bind a user group to the LDAP directory and put the people who should be
   able to sign in into it. Someone not bound to the directory is invisible to
   the search, and their login looks like an unknown username.
3. **You have a bind user.** Pick or create a service user, open its
   **Details** tab, and tick _Enable as LDAP Bind DN_. Without that its bind is
   refused and every login fails at the first step.

Then `.env`, with `YOUR_ORG_ID` substituted into all three DNs:

```dotenv
AUTH_ENABLE_LDAP=true
LDAP_SERVER_URI=ldaps://ldap.jumpcloud.com:636
LDAP_BIND_DN=uid=ldapservice,ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com
LDAP_BIND_PASSWORD=the-service-user-password

LDAP_USER_SEARCH_BASE=ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com
LDAP_USER_SEARCH_FILTER=(&(objectClass=inetOrgPerson)(uid=%(user)s))

LDAP_GROUP_SEARCH_BASE=ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com
LDAP_GROUP_TYPE=groupOfNames
LDAP_MIRROR_GROUPS=true
```

Two things about JumpCloud's tree surprise people:

- **Groups and people share one `ou=Users`.** There is no separate `ou=Groups`,
  so the user search base and the group search base are the same string. The
  `objectClass` filter is what keeps them apart.
- **A group's DN uses its name.** A user group called `engineering` is
  `cn=engineering,ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com`. Rename it in
  JumpCloud and any `LDAP_REQUIRE_GROUP` or `LDAP_STAFF_GROUP` pointing at it
  silently stops matching.

Certificates for `ldap.jumpcloud.com` are publicly signed, so leave
`LDAP_TLS_VERIFY=true` and `LDAP_CA_CERT_FILE` empty. Prefer port 636 with
`ldaps://` over 389 with STARTTLS.

### Restricting sign-in to one group

Bind a group such as `django-app` to the LDAP directory and require it:

```dotenv
LDAP_REQUIRE_GROUP=cn=django-app,ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com
LDAP_STAFF_GROUP=cn=django-admins,ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com
LDAP_SUPERUSER_GROUP=cn=django-admins,ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com
```

Removing someone from `django-app` in JumpCloud locks them out at their next
sign-in, and `LDAP_CACHE_TIMEOUT` is the longest that takes to take effect.

## Check it before you trust it

Prove the directory answers, outside Django, with the values from `.env`:

```bash
# Does the service account bind, and can it see people?
ldapsearch -H ldaps://ldap.jumpcloud.com:636 \
  -D "uid=ldapservice,ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com" -W \
  -b "ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com" \
  "(&(objectClass=inetOrgPerson)(uid=alice))"

# Which groups is that person in?
ldapsearch -H ldaps://ldap.jumpcloud.com:636 \
  -D "uid=ldapservice,ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com" -W \
  -b "ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com" \
  "(&(objectClass=groupOfNames)(member=uid=alice,ou=Users,o=YOUR_ORG_ID,dc=jumpcloud,dc=com))" cn
```

Then from Django:

```bash
LDAP_LOG_LEVEL=DEBUG python manage.py shell -c \
  "from django.contrib.auth import authenticate; print(authenticate(username='alice', password='...'))"
```

`LDAP_LOG_LEVEL=DEBUG` makes django-auth-ldap log every bind and search with
the filter it used, which is usually enough to see the problem.

| Symptom                                                     | Usually means                                                                                     |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Every login fails, the log shows the _service_ bind failing | `LDAP_BIND_DN` is wrong, or the service user does not have _Enable as LDAP Bind DN_               |
| The search returns nothing for a real person                | They are not in a user group bound to the LDAP directory, or the org ID in the base DN is wrong   |
| Login works, groups are empty                               | `LDAP_GROUP_SEARCH_BASE` is unset, or `LDAP_GROUP_TYPE` does not match the schema                 |
| `is_staff` never sticks                                     | `LDAP_STAFF_GROUP` must be a full group DN, not a group name (`manage.py check` warns about this) |
| `SERVER_DOWN`                                               | Port or TLS mismatch: `ldaps://` on 636, or `ldap://` plus `LDAP_START_TLS=true` on 389           |

An unreachable directory makes the login fail rather than raising; users see a
failed sign-in and the reason goes to the `django_auth_ldap` logger.

## Using LDAP and OIDC together

Both backends key on the Django username. The same person lands on the same
Django user only if both produce the same username — worth checking when the
OIDC provider issues emails as usernames while LDAP issues `uid`s.
`OIDC_USERNAME_CLAIM` and `LDAP_USER_SEARCH_FILTER` are the two levers; if they
cannot be reconciled, pick one backend as the source of truth for an
environment rather than running both against the same people.

Group mirroring is where the two collide hardest: with both `OIDC_SYNC_GROUPS`
and `LDAP_MIRROR_GROUPS` on, whichever backend the person last logged in
through replaces their Django groups. If both are in play, either keep the
group sets disjoint with `LDAP_MIRROR_GROUPS_ONLY`, or turn one of the two off.

## Tests

```bash
python manage.py test accounts.tests.test_ldap_settings \
                      accounts.tests.test_ldap_auth \
                      accounts.tests.test_ldap_checks
```

`accounts/tests/ldap_fake.py` is an in-memory directory that answers the handful
of python-ldap calls django-auth-ldap makes, so the real backend runs end to
end — service bind, user search, user bind, group lookup, group mirroring —
with no server and no network. It includes a small RFC 4515 filter matcher, so
the filters under test are the ones really sent.

`sample_directory()` in that module builds a JumpCloud-shaped tree: a flat
`ou=Users` holding both people and `groupOfNames` groups. To test against your
own directory's shape, change the entries there and `BASE_ENV` in
`test_ldap_auth.py`; nothing else hard-codes the schema.
