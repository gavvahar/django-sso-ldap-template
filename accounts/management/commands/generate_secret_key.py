"""Print a fresh value for DJANGO_SECRET_KEY."""

from django.core.management.base import BaseCommand
from django.core.management.utils import get_random_secret_key


class Command(BaseCommand):
    help = "Print a new random secret key suitable for DJANGO_SECRET_KEY."
    # Usable before the OIDC settings are filled in.
    requires_system_checks = []

    def handle(self, *args, **options):
        self.stdout.write(get_random_secret_key())
