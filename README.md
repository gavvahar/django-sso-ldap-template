# django-sso-ldap-template

A reusable Django project template whose login works against a self-hosted
identity provider out of the box, on top of the self-hosting tooling baseline
(linting, CI, release automation) this repo was created from.

Two login methods are wired up: SSO through OpenID Connect, and LDAP. Each is switched on independently, so a deployment can run either, both, or neither alongside Django's own passwords.

## Django project

```bash
conda env create -f environment.yml -n django-sso
conda activate django-sso
cp .env.example .env
python manage.py generate_secret_key   # paste into DJANGO_SECRET_KEY
python manage.py migrate
python manage.py runserver
```

Open <http://localhost:8000/> and use **Log in with SSO**. Until the provider
settings are filled in, `python manage.py check` reports exactly which ones are
still blank.

[docs/sso.md](docs/sso.md) covers registering the app in Authentik, the settings
that drive it, and what the template does with the provider's claims.

LDAP is off until you set `AUTH_ENABLE_LDAP=true`. Its dependency is installed
separately, because `python-ldap` is a C extension that needs OpenLDAP's headers
(`apt-get install libldap2-dev libsasl2-dev` on Debian/Ubuntu):

```bash
pip install -r requirements-ldap.txt
```

Directory groups then drive Django groups and the staff/superuser flags, and
`LDAP_REQUIRE_GROUP` / `LDAP_DENY_GROUP` turn group membership into access.
[docs/ldap.md](docs/ldap.md) covers the settings, a JumpCloud walkthrough, and
how to debug a directory that will not answer.

## Docker

```bash
cp .env.example .env    # fill in the secret key and the provider
docker compose up --build
```

One container, no web server in front of it: gunicorn with whitenoise, and
SQLite on a named volume. LDAP is installed in the image, so enabling it later
costs a restart rather than a rebuild. [docs/docker.md](docs/docker.md) covers
the first run, reverse proxies and the database.

| Path         | Purpose                                                          |
| ------------ | ---------------------------------------------------------------- |
| `manage.py`  | Django entry point                                               |
| `config/`    | Settings, URLs, WSGI/ASGI, env helpers, OIDC endpoint derivation |
| `accounts/`  | Auth backend, configuration checks, views, tests                 |
| `templates/` | Home and profile pages                                           |

Run the Django tests with `python manage.py test`, or `tox -e test` to run them
the way CI does. They need no network, no provider and no directory; the LDAP
tests drive an in-memory stand-in for a directory server, and need
`requirements-ldap.txt` installed because they exercise the real backend.

## Tooling included

- **`environment.yml` / `requirements.txt`** — conda environment (Python, pip, `gh`) with Python deps installed via pip.
- **`pyproject.toml`** — [tox](https://tox.wiki) environments for linting and formatting:
  - `lint` — `ruff check`
  - `format` — `ruff format` + `ruff check --fix` + `prettier --write` + `taplo fmt`
  - `txt-lint` — [textlint](https://textlint.github.io/) over `**/*.txt`
  - `prettier` — `prettier --check` over CSS/JS/HTML/JSON/YAML/Markdown
  - `toml-lint` — `taplo` format/lint check over TOML files
  - `duplicate-code` — [jscpd](https://github.com/kucherenko/jscpd) zero-tolerance duplicate-code scan (config in `.jscpd.json`). Real duplication should be refactored into a shared file the callers source/import, not waved off by raising the threshold.
  - `test` — the Django test suite under pytest-django
  - `github` — the full read-only CI chain (`lint` + `txt-lint` + `prettier` + `toml-lint` + `duplicate-code`)
  - `all` — `format` then `github`
  - Also configures [git-cliff](https://git-cliff.org/) for generating changelogs/PR descriptions from Conventional Commits.
- **`package.json`** — `prettier` and `textlint` (+ plugins), installed on demand by the relevant tox envs.
- **`scripts/render_env_docs.py`** — renders `*.md.template` files, substituting `${VAR}` / `${VAR:-default}` / `${VAR:?message}` references (same syntax as `compose.yml`) from `.env`. Run it via `tox -e render-docs` or `make render-docs`. Write `docs/setup.md.template`, run the renderer, and it produces `docs/setup.md` with real values filled in. **Don't use this for docs that get committed if `.env` holds secrets** — either keep the rendered output gitignored, or only template non-sensitive values (domain, ports) and leave real secrets out of the template entirely.
- **`.github/workflows/`**
  - `tests.yml` — runs `tox -e github` on every push and PR.
  - `secret-detection.yml` — [TruffleHog](https://github.com/trufflesecurity/trufflehog) scan on every push and PR.
  - `release.yml` — on push to `main`, bumps semver based on Conventional Commit prefixes (`feat` → minor, `fix`/other → patch, `!`/`BREAKING CHANGE` → major) and publishes a GitHub Release with an auto-generated changelog.
- **`CODEOWNERS`** — defaults review ownership to `@Self-Host-Server/code-owners`.
- **`.gitignore`** — editor/AI-assistant artifacts (`.vscode`, `.cursor`, `CLAUDE.md`, etc.), `.env`, `node_modules`.

## Running the checks

Install `tox` and run the full check chain locally before pushing:

```bash
pip install tox
tox -e github   # lint + txt-lint + prettier + toml-lint + duplicate-code
tox -e format   # auto-fix formatting issues
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the commit convention (Conventional Commits — it drives changelog generation and release versioning) and the local checks to run before opening a PR.
