from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_auto_20210829_0005"),
    ]

    operations = [
        migrations.DeleteModel(
            name="Media",
        ),
    ]
