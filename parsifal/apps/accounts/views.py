from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import FormView, RedirectView, UpdateView

from parsifal.apps.accounts.forms import ApiTokenForm, ProfileForm, UserEmailForm
from parsifal.apps.accounts.models import ApiToken


class SettingsRedirectView(LoginRequiredMixin, RedirectView):
    pattern_name = "settings:profile"


class UpdateProfileView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    form_class = ProfileForm
    success_url = reverse_lazy("settings:profile")
    success_message = _("Your profile was updated with success!")
    template_name = "accounts/profile.html"

    def get_object(self, queryset=None):
        return self.request.user.profile


class UpdateEmailsView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    form_class = UserEmailForm
    success_url = reverse_lazy("settings:emails")
    success_message = _("Account email was updated with success!")
    template_name = "accounts/emails.html"

    def get_object(self, queryset=None):
        return self.request.user


class ApiTokenListView(LoginRequiredMixin, FormView):
    """List the user's API tokens and create new ones. The raw key is rendered once, right after creation."""

    form_class = ApiTokenForm
    template_name = "accounts/tokens.html"

    def get_context_data(self, **kwargs):
        kwargs["tokens"] = self.request.user.api_tokens.all()
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        token, raw_key = ApiToken.create_for(self.request.user, form.cleaned_data["name"])
        messages.success(self.request, _("Token created. Copy it now: it will not be shown again."))
        context = self.get_context_data(form=self.form_class(), new_token=token, new_token_key=raw_key)
        return self.render_to_response(context)


class ApiTokenRevokeView(LoginRequiredMixin, View):
    def post(self, request, token_id):
        token = get_object_or_404(ApiToken, pk=token_id, user=request.user)
        token.revoke()
        messages.success(request, _("Token %(name)s was revoked.") % {"name": token.name})
        return redirect("settings:tokens")
