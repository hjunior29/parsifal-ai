import re

from django.db import migrations, models
from django.db.models import Count, Min


def populate_year_int(apps, schema_editor):
    Article = apps.get_model("reviews", "Article")
    for article in Article.objects.exclude(year__isnull=True).exclude(year="").iterator():
        match = re.search(r"\d{4}", article.year)
        if match:
            article.year_int = int(match.group())
            article.save(update_fields=["year_int"])


def remove_duplicates(apps, schema_editor):
    """
    The uniqueness the application always assumed was never enforced; drop any duplicate rows (keeping the
    oldest) before adding the constraints.
    """
    QualityAssessment = apps.get_model("reviews", "QualityAssessment")
    DataExtraction = apps.get_model("reviews", "DataExtraction")
    SearchSession = apps.get_model("reviews", "SearchSession")

    def dedupe(queryset, *fields):
        groups = queryset.values(*fields).annotate(total=Count("id"), keep=Min("id")).filter(total__gt=1)
        for group in groups:
            lookup = {field: group[field] for field in fields}
            queryset.filter(**lookup).exclude(pk=group["keep"]).delete()

    dedupe(QualityAssessment.objects.all(), "article", "question")
    dedupe(DataExtraction.objects.all(), "article", "field")
    dedupe(SearchSession.objects.exclude(source__isnull=True), "review", "source")
    dedupe(SearchSession.objects.filter(source__isnull=True), "review")


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0037_auto_20210910_0311"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="year_int",
            field=models.IntegerField(
                blank=True, db_index=True, editable=False, null=True, verbose_name="year (numeric)"
            ),
        ),
        migrations.RunPython(populate_year_int, migrations.RunPython.noop),
        migrations.RunPython(remove_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="searchsession",
            constraint=models.UniqueConstraint(fields=("review", "source"), name="unique_search_session_per_source"),
        ),
        migrations.AddConstraint(
            model_name="searchsession",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source__isnull", True)), fields=("review",), name="unique_generic_search_session"
            ),
        ),
        migrations.AddConstraint(
            model_name="qualityassessment",
            constraint=models.UniqueConstraint(
                fields=("article", "question"), name="unique_quality_assessment_per_question"
            ),
        ),
        migrations.AddConstraint(
            model_name="dataextraction",
            constraint=models.UniqueConstraint(fields=("article", "field"), name="unique_data_extraction_per_field"),
        ),
    ]
