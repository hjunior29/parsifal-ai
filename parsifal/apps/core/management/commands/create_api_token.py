from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from parsifal.apps.accounts.models import ApiToken


class Command(BaseCommand):
    help = "Create a personal API token for a user and print it (it is shown only once)."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username of the token owner.")
        parser.add_argument("--name", default="CLI", help="Label for the token (default: CLI).")

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username__iexact=options["user"], is_active=True)
        except User.DoesNotExist:
            raise CommandError(f"User {options['user']!r} not found.")
        token, raw_key = ApiToken.create_for(user, options["name"])
        self.stderr.write(f"Token '{token.name}' created for {user.username}. Store it now; it cannot be shown again.")
        self.stdout.write(raw_key)
