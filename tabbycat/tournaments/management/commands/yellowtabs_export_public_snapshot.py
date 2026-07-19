"""Build an offline, anonymous public browse bundle for one Tabbycat instance.

Called only by YellowTabs' fixed host exporter. This command deliberately uses
Django's in-process client: no network listener, cookies or external URLs are
needed while a tenant is being prepared for hibernation.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import deque
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import Client, override_settings


MAX_ENTRIES = 10_000
MAX_BYTES = 128 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
UNSAFE_PREFIXES = ("/admin/", "/database/", "/allocation/", "/notifications/", "/accounts/", "/login/")
LINK_RE = re.compile(r'''(?:href|src)=["']([^"'#]+)''', re.I)


def canonical(value: str) -> str | None:
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not parts.path.startswith("/") or "\\" in parts.path:
        return None
    if any(parts.path.startswith(prefix) for prefix in UNSAFE_PREFIXES):
        return None
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit(("", "", parts.path, query, ""))


class Command(BaseCommand):
    help = "Export anonymous GET browse responses into a validated YellowTabs snapshot bundle."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)
        parser.add_argument("--host", required=True)

    def handle(self, *args, **options):
        target = Path(options["output"]).resolve()
        if target.exists() and any(target.iterdir()):
            raise CommandError("snapshot output must be empty")
        target.mkdir(parents=True, exist_ok=True)
        bodies = target / "bodies"
        bodies.mkdir()
        queue = deque(["/"])
        seen = set()
        entries = {}
        total = 0

        # Snapshot is one DB view even if concurrent writes continue. Never use
        # cache: result must be a direct rendering of this transaction.
        with override_settings(ALLOWED_HOSTS=["*"], CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            client = Client(HTTP_HOST=options["host"])
            while queue:
                url = queue.popleft()
                if url in seen:
                    continue
                seen.add(url)
                if len(seen) > MAX_ENTRIES:
                    raise CommandError("snapshot exceeds response limit")
                response = client.get(url, HTTP_ACCEPT_LANGUAGE="en")
                # Snapshot gateway rejects cookie-bearing requests before lookup.
                # Django's anonymous pages commonly still declare Vary: Cookie;
                # no Set-Cookie response means this cookie-free representation is
                # safe to publish.
                if response.cookies or response.status_code >= 400:
                    continue
                body = bytes(response.content) if not response.streaming else b""
                if len(body) > MAX_RESPONSE_BYTES:
                    raise CommandError("snapshot response exceeds byte limit")
                total += len(body)
                if total > MAX_BYTES:
                    raise CommandError("snapshot exceeds tenant byte limit")
                body_name = hashlib.sha256(url.encode()).hexdigest()
                (bodies / body_name).write_bytes(body)
                headers = {name: response[name] for name in ("Content-Type", "Content-Language", "Cache-Control", "ETag", "Last-Modified", "Location") if response.has_header(name)}
                entries["GET " + url] = {
                    "status": response.status_code,
                    "headers": headers,
                    "body": "bodies/" + body_name,
                    "length": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
                if 300 <= response.status_code < 400:
                    redirect = canonical(response.get("Location", ""))
                    if redirect and redirect not in seen:
                        queue.append(redirect)
                if response.get("Content-Type", "").split(";", 1)[0] == "text/html":
                    for raw in LINK_RE.findall(body.decode("utf-8", "ignore")):
                        candidate = canonical(raw)
                        if candidate and candidate not in seen:
                            queue.append(candidate)

        if not entries:
            # `target` can be a Docker bind mount. Its mountpoint cannot be
            # removed from inside the exporter, but its generated contents can.
            shutil.rmtree(bodies)
            raise CommandError("no snapshot-safe public responses were produced")
        manifest = {"format_version": 1, "entries": entries}
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        (target / "manifest.json").write_bytes(manifest_bytes)
        self.stdout.write(json.dumps({"entry_count": len(entries), "byte_count": total, "checksum": hashlib.sha256(manifest_bytes).hexdigest()}))
