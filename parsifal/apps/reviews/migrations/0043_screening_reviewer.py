from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("reviews", "0042_ai_screening"),
    ]

    operations = [
        # Runs are made in the name of a reviewer chosen at start, no longer of a dedicated Jev agent.
        migrations.RenameField(model_name="screeningrun", old_name="agent", new_name="reviewer"),
        migrations.AlterField(
            model_name="screeningrun",
            name="reviewer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="screening_runs", to=settings.AUTH_USER_MODEL
            ),
        ),
        migrations.RemoveField(model_name="reviewagent", name="kind"),
        migrations.AddField(
            model_name="screeningresult",
            name="previous_status",
            field=models.CharField(blank=True, max_length=1, verbose_name="status before the run"),
        ),
    ]
