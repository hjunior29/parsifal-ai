from django.contrib import admin

from parsifal.apps.accounts.models import ApiToken, Integration


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "user", "created_at", "last_used_at", "revoked_at")
    list_select_related = ("user",)
    list_filter = ("revoked_at",)
    search_fields = ("name", "prefix", "user__username", "user__email")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")
    raw_id_fields = ("user",)

    def has_add_permission(self, request):
        # Tokens are only created through the settings page or the CLI, where the raw key can be shown once.
        return False


@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "model", "masked_key", "updated_at")
    list_select_related = ("user",)
    exclude = ("api_key",)  # never rendered back; users replace it in Settings → Integrations
    readonly_fields = ("masked_key", "created_at", "updated_at")
    raw_id_fields = ("user",)

    def has_add_permission(self, request):
        return False
