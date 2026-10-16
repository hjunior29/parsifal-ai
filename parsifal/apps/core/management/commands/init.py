import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.validators import ASCIIUsernameValidator, validate_forbidden_usernames
from parsifal.apps.core.management.commands.load_default_sources import load_default_sources

INSECURE_SECRET_KEYS = {"parsifal.settings.local", "change-me", ""}


class Command(BaseCommand):
    help = (
        "Bootstrap a self-hosted instance: apply migrations, load the default digital libraries, "
        "create the administrator account and, optionally, an API token for it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username", required=True, help="Administrator username (not a reserved word such as admin)."
        )
        parser.add_argument("--email", default="", help="Administrator e-mail.")
        parser.add_argument(
            "--password",
            default=None,
            help="Administrator password. Omit to generate a random one, which is printed once.",
        )
        parser.add_argument(
            "--token",
            metavar="NAME",
            default=None,
            help="Also create an API token with this name for the administrator and print it.",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        self.stdout.write("Applying migrations...")
        call_command("migrate", interactive=False, verbosity=0)

        created_sources = load_default_sources()
        self.stdout.write(f"Default sources: {len(created_sources)} created.")

        username = options["username"]
        try:
            # Review pages live at /<username>/..., so names that collide with site routes (admin, docs, api...)
            # would make the administrator's reviews unreachable.
            ASCIIUsernameValidator()(username)
            validate_forbidden_usernames(username)
        except ValidationError as error:
            raise CommandError(f"Invalid username {username!r}: {' '.join(error.messages)}")
        user = User.objects.filter(username__iexact=username).first()
        generated_password = None
        if user is None:
            password = options["password"]
            if not password:
                password = generated_password = secrets.token_urlsafe(16)
            user = User.objects.create_superuser(username=username, email=options["email"], password=password)
            self.stdout.write(f"Administrator '{username}' created.")
        else:
            if not user.is_superuser:
                raise CommandError(f"User '{username}' exists but is not an administrator.")
            self.stdout.write(f"Administrator '{username}' already exists; password unchanged.")

        if generated_password:
            self.stdout.write(self.style.WARNING(f"Generated password for '{username}': {generated_password}"))

        if options["token"]:
            token, raw_key = ApiToken.create_for(user, options["token"])
            self.stdout.write(self.style.WARNING(f"API token '{token.name}': {raw_key}"))

        if settings.SECRET_KEY in INSECURE_SECRET_KEYS:
            self.stdout.write(
                self.style.WARNING(
                    "SECRET_KEY is not set. Before exposing this instance, add to .env:\n"
                    f"  SECRET_KEY={secrets.token_urlsafe(50)}"
                )
            )
        self.stdout.write(self.style.SUCCESS("Parsifal is ready."))
