from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext, gettext_lazy as _
from django.views import View
from django.views.generic import FormView, RedirectView, UpdateView

from parsifal.apps.accounts import services
from parsifal.apps.accounts.forms import ApiTokenForm, JevIntegrationForm, ProfileForm, UserEmailForm, model_label
from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.core import jev
from parsifal.apps.core.exceptions import DomainError


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


class ApiTokenDeleteView(LoginRequiredMixin, View):
    """Delete a token for good; only a revoked token can be deleted."""

    def post(self, request, token_id):
        token = get_object_or_404(ApiToken, pk=token_id, user=request.user)
        if token.is_active:
            messages.error(request, _("Revoke the token %(name)s before deleting it.") % {"name": token.name})
        else:
            token.delete()
            messages.success(request, _("Token %(name)s was deleted.") % {"name": token.name})
        return redirect("settings:tokens")


class IntegrationModelsView(LoginRequiredMixin, View):
    """Jev's models for the key being typed (or the saved one), so the page fills the select before saving."""

    def post(self, request):
        try:
            models = services.test_jev(request.user, api_key=request.POST.get("api_key"))
        except DomainError as error:
            return JsonResponse({"error": str(error)}, status=400)
        return JsonResponse({"models": [{"name": m["name"], "label": model_label(m)} for m in models]})


class IntegrationsView(LoginRequiredMixin, View):
    """
    Third-party services the user connected. Jev: save or replace the API key and the model, check that the key
    works, or remove it. The saved key is never rendered back, only its last characters.
    """

    template_name = "accounts/integrations.html"

    def _models(self, integration, api_key=None):
        """Jev's model list, asked on every page load: with the key being saved, else the saved one."""
        if api_key or integration:
            return services.jev_models(self.request.user, api_key=api_key)
        return [], ""

    def _render(self, form=None, models=None, models_error=""):
        integration = services.get_jev(self.request.user)
        if form is None:
            models, models_error = self._models(integration)
            form = JevIntegrationForm(
                initial={"model": integration.model if integration else jev.DEFAULT_MODEL},
                has_key=integration is not None,
                models=models,
                current_model=integration.model if integration else None,
                models_error=models_error,
            )
        context = {"jev": integration, "form": form, "models_error": models_error}
        return render(self.request, self.template_name, context)

    def get(self, request):
        return self._render()

    def post(self, request):
        action = request.POST.get("action")
        if action == "remove":
            if services.remove_jev(request.user):
                messages.success(request, gettext("The Jev API key was removed."))
            return redirect("settings:integrations")
        if action == "test":
            try:
                models = services.test_jev(request.user)
            except DomainError as error:
                messages.error(request, str(error))
            else:
                available = ", ".join(model["name"] for model in models) or gettext("none listed")
                messages.success(
                    request, gettext("Jev accepted the key. Models available: %(models)s.") % {"models": available}
                )
            return redirect("settings:integrations")
        integration = services.get_jev(request.user)
        models, models_error = self._models(integration, api_key=request.POST.get("api_key", "").strip() or None)
        form = JevIntegrationForm(
            request.POST,
            has_key=integration is not None,
            models=models,
            current_model=integration.model if integration else None,
            models_error=models_error,
        )
        if not form.is_valid():
            return self._render(form, models, models_error)
        services.save_jev(request.user, api_key=form.cleaned_data["api_key"], model=form.cleaned_data["model"])
        messages.success(request, gettext("Jev settings saved."))
        return redirect("settings:integrations")
