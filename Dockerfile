# syntax=docker/dockerfile:1

# Two stages: the first builds the Python dependencies, the second copies the
# finished virtualenv into a clean image. python-ldap is a C extension, so the
# compiler and OpenLDAP's headers are needed to install it but not to run it.

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS build

# Whether to install requirements-ldap.txt. Leave it on to have
# AUTH_ENABLE_LDAP=true work without rebuilding; turn it off for a smaller
# image if the deployment signs people in through SSO alone.
ARG INSTALL_LDAP=true

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        build-essential \
        libldap2-dev \
        libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
COPY requirements.txt requirements-ldap.txt ./
RUN pip install --requirement requirements.txt \
    && if [ "${INSTALL_LDAP}" = "true" ]; then \
        pip install --requirement requirements-ldap.txt; \
    fi

FROM python:${PYTHON_VERSION}-slim AS runtime

# The shared libraries python-ldap links against, without the headers and the
# compiler. OpenLDAP 2.6 renamed the runtime package from libldap-2.5-0 to
# libldap2, so either name satisfies this, whichever Debian the base image is
# on. Harmless when the image was built with INSTALL_LDAP=false.
RUN apt-get update \
    && apt-get satisfy --no-install-recommends --yes \
        "libldap2 | libldap-2.5-0" \
        "libsasl2-2" \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY . .

# Collected here at build time rather than on every start. It needs no
# database and no provider, so the placeholder settings are enough; whitenoise
# serves the result, which is why no web server sits in front of gunicorn.
RUN python manage.py collectstatic --noinput --clear

# Runs unprivileged, and owns the directory compose mounts the database on.
RUN useradd --create-home --uid 10001 django \
    && mkdir -p /var/lib/django \
    && chown django /var/lib/django
USER django

EXPOSE 8000
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
# Override the worker count, timeouts or log level with GUNICORN_CMD_ARGS,
# which gunicorn reads from the environment.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
