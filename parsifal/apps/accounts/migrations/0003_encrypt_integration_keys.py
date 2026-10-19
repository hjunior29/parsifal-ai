from django.db import migrations, models

from parsifal.apps.core import crypto


def encrypt_keys(apps, schema_editor):
    Integration = apps.get_model("accounts", "Integration")
    for integration in Integration.objects.all():
        raw = integration.api_key
        integration.api_key_encrypted = crypto.encrypt(raw)
        integration.key_hint = raw[-4:] if len(raw) > 8 else ""
        integration.save(update_fields=["api_key_encrypted", "key_hint"])


def decrypt_keys(apps, schema_editor):
    Integration = apps.get_model("accounts", "Integration")
    for integration in Integration.objects.all():
        try:
            integration.api_key = crypto.decrypt(integration.api_key_encrypted)
        except crypto.DecryptionError:
            integration.api_key = ""
        integration.save(update_fields=["api_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_integrations"),
    ]

    operations = [
        migrations.AddField(
            model_name="integration",
            name="api_key_encrypted",
            field=models.TextField(default="", verbose_name="API key (encrypted)"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="integration",
            name="key_hint",
            field=models.CharField(blank=True, max_length=4, verbose_name="last characters of the API key"),
        ),
        migrations.RunPython(encrypt_keys, decrypt_keys),
        # A default so that reversing the removal can add the column back before the keys are decrypted into it.
        migrations.AlterField(
            model_name="integration",
            name="api_key",
            field=models.CharField(default="", max_length=500, verbose_name="API key"),
        ),
        migrations.RemoveField(
            model_name="integration",
            name="api_key",
        ),
        migrations.AlterField(
            model_name="integration",
            name="model",
            field=models.CharField(max_length=100, verbose_name="default model"),
        ),
    ]
