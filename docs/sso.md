# SSO login (OpenID Connect)

Login runs through an OpenID Connect provider using
[mozilla-django-oidc](https://mozilla-django-oidc.readthedocs.io/), with the
authorization code flow and PKCE. [Authentik](https://goauthentik.io/) is the
reference provider, but nothing in the code is Authentik-specific: any OIDC
provider works once its endpoints are in `.env`.

## Registering the app in Authentik

1. Go to **Applications → Providers → Create** and pick
   **OAuth2/OpenID Provider**.
2. Set:
   - **Name**: anything, for example `Django SSO template`
   - **Authorization flow**: your usual explicit or implicit consent flow
   - **Client type**: `Confidential`
   - **Redirect URIs**: `http://localhost:8000/oidc/callback/`
     (add the production URL too, one per line, when you deploy)
   - **Signing key**: the certificate to sign tokens with — this makes the
     provider sign with RS256, which is what `OIDC_RP_SIGN_ALGO` expects
3. Save, then copy the **Client ID** and **Client Secret**.
4. Go to **Applications → Create**, give the application a slug (for example
   `django-sso-template`) and select the provider you just made.
5. Open the provider page again and copy the **OpenID Configuration Issuer**
   value. It looks like
   `https://authentik.example.com/application/o/django-sso-template/`.
6. Put those three values in `.env`:

   ```ini
   OIDC_ISSUER=https://authentik.example.com/application/o/django-sso-template/
   OIDC_RP_CLIENT_ID=...
   OIDC_RP_CLIENT_SECRET=...
   ```

`python manage.py check` reports any OIDC setting that is still blank, so run it
first if login does not come up.

## Endpoints

The authorize, token, userinfo, JWKS and end-session endpoints are derived from
`OIDC_ISSUER` using Authentik's URL layout (`config/oidc.py`), so startup never
depends on reaching the provider. To pin them explicitly instead — or to point
the template at a different provider — run:

```bash
python manage.py oidc_discover
```

It reads the provider's `.well-known/openid-configuration` and prints the
`OIDC_OP_*` lines to paste into `.env`. Any endpoint set in the environment wins
over the derived one.

## Which login methods are enabled

`AUTHENTICATION_BACKENDS` is assembled from environment toggles rather than
hardcoded, so each method switches on independently:

- `AUTH_ENABLE_OIDC` (default `true`) — SSO through the provider. With it off,
  the OIDC configuration checks stand down as well, so a deployment that does
  not use SSO does not have to fill in the provider settings.
- `AUTH_ENABLE_LOCAL_PASSWORDS` (default `true`) — Django's own passwords, so a
  `createsuperuser` account can still reach the admin if the provider is
  unreachable. Set it to `false` to make SSO the only way in.

Enabling none of them raises `ImproperlyConfigured` at startup rather than
silently locking everyone out.

## What happens at login

`accounts/auth.py` maps the provider's claims onto the Django user on every
login, so the provider stays the source of truth:

| Claim                                           | Django user                                      |
| ----------------------------------------------- | ------------------------------------------------ |
| `preferred_username` (or `OIDC_USERNAME_CLAIM`) | `username`, falling back to the email local part |
| `email`                                         | `email`; also how an existing user is matched    |
| `given_name` / `family_name`, else `name`       | `first_name` / `last_name`                       |
| `groups` (or `OIDC_GROUPS_CLAIM`)               | `groups`, and `is_staff` / `is_superuser`        |

Set `OIDC_CREATE_USER=false` to allow only users that already exist in Django.

### Group sync

Authentik does not send group membership with the standard scopes. To get it:

1. **Customisation → Property Mappings → Create → Scope Mapping**, with scope
   name `groups` and expression:

   ```python
   return [group.name for group in request.user.ak_groups.all()]
   ```

2. Add that mapping to the provider's **Scopes**.
3. Set `OIDC_RP_SCOPES=openid email profile groups` in `.env`.

With `OIDC_SYNC_GROUPS=true` (the default) every login replaces the user's
Django groups with the ones in the claim, creating any that do not exist yet, so
permissions can be attached to them in the admin. Point `OIDC_STAFF_GROUP` and
`OIDC_SUPERUSER_GROUP` at provider group names to drive those flags from
Authentik too.

## URLs

| Path                  | Purpose                                     |
| --------------------- | ------------------------------------------- |
| `/`                   | Public home page with the login button      |
| `/profile/`           | `@login_required`; shows the mapped claims  |
| `/oidc/authenticate/` | Starts the flow (this is `LOGIN_URL`)       |
| `/oidc/callback/`     | Redirect URI registered in Authentik        |
| `/oidc/logout/`       | POST; ends the Django and provider sessions |
| `/admin/`             | Django admin, reachable by staff users      |

Logout is RP-initiated: `accounts.auth.provider_logout_url` sends the stored id
token as `id_token_hint` to the provider's end-session endpoint, so signing out
of the app ends the provider session too.

## Deploying

- Set `DJANGO_DEBUG=false` and a real `DJANGO_SECRET_KEY`.
- Set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` to your domain.
- Add the production `https://…/oidc/callback/` to the provider's redirect URIs.
- Serve over https. Behind a TLS-terminating proxy, forward `X-Forwarded-Proto`
  so the redirect URI is built as `https` (`SECURE_PROXY_SSL_HEADER` is already
  set for this).
- Swap the SQLite database in `config/settings.py` for your real one.

## Troubleshooting

Set `OIDC_LOG_LEVEL=DEBUG` in `.env` to see what mozilla-django-oidc and the
backend are doing. `OIDC_RENEW_SESSION` (default on) re-validates the session
against the provider every `OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS`, so a user
disabled in Authentik loses access without waiting for the Django session to
expire.
