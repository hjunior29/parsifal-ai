from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0043_screening_reviewer"),
    ]

    operations = [
        migrations.AddField(
            model_name="screeningrun",
            name="last_step_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="screeningrun",
            name="error",
            field=models.CharField(blank=True, max_length=500, verbose_name="error"),
        ),
        migrations.AlterField(
            model_name="screeningrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("running", "Running"),
                    ("finished", "Finished"),
                    ("cancelled", "Discarded"),
                    ("failed", "Failed"),
                ],
                default="running",
                max_length=10,
                verbose_name="status",
            ),
        ),
    ]
