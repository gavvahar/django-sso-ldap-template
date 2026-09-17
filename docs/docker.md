# Running it with Docker

`compose.yml` runs the whole template as one container: gunicorn serving the
Django project, whitenoise serving the static files it collected at build time,
and SQLite on a named volume. Nothing else is needed in front of it to get a
login working, and nothing in the image is specific to a provider or a
directory — every setting comes from the environment, exactly as it does when
you run the project with `manage.py runserver`.

## First run

```bash
cp .env.example .env
docker compose run --rm web python manage.py generate_secret_key
```

Paste that key into `DJANGO_SECRET_KEY`, fill in `OIDC_RP_CLIENT_ID` and
`OIDC_RP_CLIENT_SECRET` from your provider (see [sso.md](sso.md)), then:

```bash
docker compose up --build
```

The site is on <http://localhost:8000/>, or on `DJANGO_PORT` if you set it to
something else. Migrations are applied on every start, so there is no separate
step for them.

Django refuses to start while SSO is switched on and half-configured: the log
names each setting that is still blank, which is the same report
`manage.py check` gives. To bring the stack up before you have a provider, set
`AUTH_ENABLE_OIDC=false` and sign in with a local account instead:

```bash
docker compose exec web python manage.py createsuperuser
```

That account reaches `/admin/` regardless of what the provider is doing, which
is why `AUTH_ENABLE_LOCAL_PASSWORDS` defaults to true.

## LDAP

The image installs `requirements-ldap.txt` by default, so switching
`AUTH_ENABLE_LDAP=true` in `.env` and restarting is all that a directory login
needs — no rebuild, and none of the system packages python-ldap wants on the
host. Set `INSTALL_LDAP=false` to leave it out and get a smaller image; the
setting then has nothing to import. [ldap.md](ldap.md) covers the rest.

## Behind a reverse proxy

Add the public hostname to `DJANGO_ALLOWED_HOSTS` and the public origin to
`DJANGO_CSRF_TRUSTED_ORIGINS`, and have the proxy pass `X-Forwarded-Proto`:
the project trusts that header, so the redirect URI it sends to the provider is
built as `https://` even though gunicorn itself speaks plain HTTP on the
container port.

Leave `DJANGO_DEBUG=false` there. It is what turns on the secure session and
CSRF cookies.

## Day to day

- **Logs** — `docker compose logs -f web`. Set `OIDC_LOG_LEVEL=DEBUG` or
  `LDAP_LOG_LEVEL=DEBUG` in `.env` to have a refused login explain itself.
- **A shell** — `docker compose exec web python manage.py shell`.
- **The database** — it lives on the `django-data` volume as
  `db.sqlite3`, so a rebuild keeps it. `docker compose down -v` deletes it.
- **After changing `requirements.txt`** — `docker compose up --build`, since
  the dependencies are installed into the image rather than at start-up.
- **Health** — compose polls the home page and marks the container unhealthy if
  Django stops answering. `docker compose ps` shows the verdict.

## Using PostgreSQL instead

`config/settings.py` configures SQLite only, so a Postgres service is not a
matter of adding it to `compose.yml`: point `DATABASES["default"]` at it (and
add `psycopg` to `requirements.txt`) first. SQLite is the default here because
the template's own tables are Django's, and one file on a volume is one less
thing to run.
