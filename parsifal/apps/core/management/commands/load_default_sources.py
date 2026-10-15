import json
from pathlib import Path

from django.core.management.base import BaseCommand

from parsifal.apps.reviews.models import Source

FIXTURE = Path(__file__).resolve().parents[3] / "reviews" / "fixtures" / "source_initial_data.json"


def load_default_sources():
    """Create the default digital libraries from the fixture, matching by name so it is safe to re-run."""
    created = []
    for row in json.loads(FIXTURE.read_text()):
        fields = row["fields"]
        source, was_created = Source.objects.get_or_create(
            name=fields["name"], defaults={"url": fields["url"], "is_default": True}
        )
        if not source.is_default:
            source.is_default = True
            source.save(update_fields=["is_default"])
        if was_created:
            created.append(source)
    return created


class Command(BaseCommand):
    help = "Load the default digital libraries (Scopus, IEEE, ACM, ...) without duplicating existing ones."

    def handle(self, *args, **options):
        created = load_default_sources()
        self.stdout.write(
            f"{len(created)} default source(s) created; {Source.objects.filter(is_default=True).count()} available."
        )
