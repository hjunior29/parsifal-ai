from django.urls import path

from parsifal.apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("", views.SettingsRedirectView.as_view(), name="settings"),
    path("profile/", views.UpdateProfileView.as_view(), name="profile"),
    path("emails/", views.UpdateEmailsView.as_view(), name="emails"),
    path("tokens/", views.ApiTokenListView.as_view(), name="tokens"),
    path("tokens/<int:token_id>/revoke/", views.ApiTokenRevokeView.as_view(), name="token_revoke"),
    path("tokens/<int:token_id>/delete/", views.ApiTokenDeleteView.as_view(), name="token_delete"),
    path("integrations/", views.IntegrationsView.as_view(), name="integrations"),
]
