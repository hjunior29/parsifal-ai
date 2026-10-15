from django.contrib import admin

from parsifal.apps.accounts.models import ApiToken


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
