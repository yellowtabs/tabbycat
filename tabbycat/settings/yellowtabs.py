# ==============================================================================
# YellowTabs
# ==============================================================================
#
# Env-driven production settings for YellowTabs managed hosting. Modelled on the
# upstream `heroku.py` settings module but targets a *shared* Postgres + Redis
# backing many container-per-tournament deployments.
#
# This file is part of YellowTabs' AGPL-3.0 source changes to Tabbycat and is
# mirrored verbatim in our public fork. It is selected by `__init__.py` when the
# environment variable `ON_YELLOWTABS` is set (see the accompanying patch).
#
# Install location in the fork: tabbycat/settings/yellowtabs.py
# ==============================================================================

import logging
from os import environ

import dj_database_url
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from .core import TABBYCAT_VERSION

# ------------------------------------------------------------------------------
# Identity / security
# ------------------------------------------------------------------------------

# Each tournament container is injected a unique key by the provisioner.
if environ.get('DJANGO_SECRET_KEY', ''):
    SECRET_KEY = environ['DJANGO_SECRET_KEY']

# We terminate TLS at Cloudflare/front-Nginx, so trust the forwarded proto.
ALLOWED_HOSTS = ['*']
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Default: do NOT issue in-app HTTPS redirects (TLS is terminated upstream;
# an in-app redirect behind the proxy causes loops). Set
# DISABLE_HTTPS_REDIRECTS to anything other than 'disable' to re-enable them.
if environ.get('DISABLE_HTTPS_REDIRECTS', 'disable') != 'disable':
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Cookies are still served over HTTPS end-to-end via Cloudflare; mark secure
# unless explicitly disabled above is off. Cookies set secure by default:
SESSION_COOKIE_SECURE = environ.get('COOKIE_SECURE', 'true').lower() == 'true'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# Tab director email, stored for reporting (optional).
if environ.get('TAB_DIRECTOR_EMAIL', ''):
    TAB_DIRECTOR_EMAIL = environ['TAB_DIRECTOR_EMAIL']

# ------------------------------------------------------------------------------
# Database — shared Postgres, one DB per tournament (via PgBouncer)
# ------------------------------------------------------------------------------
#
# DATABASE_URL points at the tournament's own database on the shared cluster,
# normally through PgBouncer in transaction-pooling mode, e.g.
#   postgres://<slug>:<pw>@pgbouncer:6432/<slug>
#
# Transaction pooling is incompatible with server-side cursors and persistent
# connections, so we disable both. See docs/adr for the rationale.

DATABASES = {
    'default': dj_database_url.config(
        default='postgres://localhost',
        conn_max_age=0,
    ),
}
DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = (
    environ.get('DISABLE_SERVER_SIDE_CURSORS', 'true').lower() == 'true'
)

# ------------------------------------------------------------------------------
# Redis / Channels — shared Redis, one logical DB index per tournament
# ------------------------------------------------------------------------------
#
# REDIS_URL carries the per-tournament DB index, e.g. redis://redis:6379/7.
# Both the cache and the Channels layer use the SAME url so they share the
# tournament's isolated logical DB. (Redis exposes 16 DBs 0..15 by default.)

REDIS_URL = environ.get('REDIS_URL', 'redis://localhost:6379/0')

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 60,
            "IGNORE_EXCEPTIONS": True,  # don't 500 if Redis blips
        },
    },
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            # Drop channels from groups after 3h, matching Daphne's
            # websocket_timeout — same value upstream uses.
            "group_expiry": 10800,
        },
    },
}

# ------------------------------------------------------------------------------
# Email — shared AWS SES SMTP across all tournaments
# ------------------------------------------------------------------------------
#
# One verified sending domain; Tabbycat sets the From *display name* to the
# tournament name automatically, so no per-tournament email config is needed.

if environ.get('EMAIL_HOST', ''):
    DEFAULT_FROM_EMAIL = environ['DEFAULT_FROM_EMAIL']
    SERVER_EMAIL = DEFAULT_FROM_EMAIL
    EMAIL_HOST = environ['EMAIL_HOST']
    EMAIL_HOST_USER = environ['EMAIL_HOST_USER']
    EMAIL_HOST_PASSWORD = environ['EMAIL_HOST_PASSWORD']
    EMAIL_PORT = int(environ.get('EMAIL_PORT', 587))
    EMAIL_USE_TLS = environ.get('EMAIL_USE_TLS', 'true').lower() == 'true'

# ------------------------------------------------------------------------------
# Source-code link (AGPL §13) — surfaced in the footer template patch
# ------------------------------------------------------------------------------

YELLOWTABS_SOURCE_URL = environ.get(
    'YELLOWTABS_SOURCE_URL',
    'https://github.com/yellowtabs/tabbycat',
)

# ------------------------------------------------------------------------------
# Sentry — disabled by default; our tenants must not report to upstream's DSN
# ------------------------------------------------------------------------------

if not environ.get('DISABLE_SENTRY'):
    DISABLE_SENTRY = False
    sentry_sdk.init(
        dsn=environ.get('SENTRY_DSN', ''),
        integrations=[
            DjangoIntegration(),
            LoggingIntegration(event_level=logging.WARNING),
            RedisIntegration(),
        ],
        send_default_pii=True,
        release=TABBYCAT_VERSION,
    )
