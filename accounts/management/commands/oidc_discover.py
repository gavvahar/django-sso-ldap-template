"""Print the OIDC endpoint settings for an issuer, read from its discovery document."""

import json
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.oidc import ENDPOINT_KEYS


class Command(BaseCommand):
    help = (
        "Fetch <issuer>/.well-known/openid-configuration and print the matching "
        ".env lines, so endpoints can be pinned instead of derived."
    )

    # This command is how you find the endpoints, so it must run before the
    # configuration checks would pass.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "issuer",
            nargs="?",
            default=settings.OIDC_ISSUER,
            help="Issuer URL; defaults to OIDC_ISSUER from the environment.",
        )
        parser.add_argument(
            "--timeout", type=float, default=10.0, help="Request timeout in seconds."
        )

    def handle(self, *args, **options):
        issuer = (options["issuer"] or "").rstrip("/")
        if not issuer:
            raise CommandError("No issuer given and OIDC_ISSUER is not set.")

        url = f"{issuer}/.well-known/openid-configuration"
        self.stdout.write(f"# fetched from {url}")
        try:
            with urllib.request.urlopen(url, timeout=options["timeout"]) as response:
                document = json.load(response)
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the operator
            raise CommandError(f"Could not read {url}: {exc}") from exc

        for claim, setting in ENDPOINT_KEYS.items():
            value = document.get(claim)
            if value:
                self.stdout.write(f"{setting}={value}")
            else:
                self.stdout.write(
                    self.style.WARNING(f"# {setting}: provider advertises no {claim}")
                )
