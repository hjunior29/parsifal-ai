from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext, gettext_lazy as _

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.models import Profile


class UserEmailForm(forms.ModelForm):
    email = forms.CharField(
        label=_("Email"),
        widget=forms.EmailInput(attrs={"class": "form-control"}),
        max_length=254,
        help_text=_(
            "This email account will not be publicly available. "
            "It is used for your Parsifal account management, "
            "such as internal notifications and password reset."
        ),
    )

    class Meta:
        model = User
        fields = ("email",)

    def clean_email(self):
        email = self.cleaned_data.get("email")
        email = User.objects.normalize_email(email)
        if User.objects.exclude(pk=self.instance.pk).filter(email__iexact=email).exists():
            raise ValidationError(gettext("User with this Email already exists."))
        return email


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(label=_("First name"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Last name"), max_length=150, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].initial = self.instance.user.first_name
        self.fields["last_name"].initial = self.instance.user.last_name

    class Meta:
        model = Profile
        fields = ()

    @transaction.atomic()
    def save(self, commit=True):
        self.instance.user.first_name = self.cleaned_data["first_name"]
        self.instance.user.last_name = self.cleaned_data["last_name"]
        if commit:
            self.instance.user.save()
        return super().save(commit)


def model_label(model):
    details = " · ".join(value for value in (model.get("description"), model.get("release_date")) if value)
    return f"{model['name']} — {details}" if details else model["name"]


class JevIntegrationForm(forms.Form):
    """API key and model for Jev. A blank key keeps the one already saved."""

    api_key = forms.CharField(
        label=_("API key"),
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "off"}),
        max_length=500,
        required=False,
    )
    model = forms.CharField(
        label=_("Model"),
        widget=forms.TextInput(attrs={"class": "form-control"}),
        max_length=100,
        help_text=_(
            "Pin a version such as jev-1.13.0 so that results stay reproducible; aliases like jev-latest change "
            "without notice."
        ),
    )

    def __init__(self, *args, has_key=False, models=(), current_model=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_key = has_key
        if has_key:
            self.fields["api_key"].help_text = _("Leave blank to keep the current key.")
        if models:
            # Jev's own list, asked when the page loads; the saved default stays selectable even if Jev dropped it.
            choices = [(m["name"], model_label(m)) for m in models]
            if current_model and current_model not in {m["name"] for m in models}:
                choices.append((current_model, gettext("%(model)s (not listed by Jev)") % {"model": current_model}))
            self.fields["model"] = forms.ChoiceField(
                label=_("Default model"),
                choices=choices,
                widget=forms.Select(attrs={"class": "form-control"}),
                help_text=_(
                    "Models available to your key, as listed by Jev. This is the default for Exclude with AI; each "
                    "run can use another one. Prefer a pinned version (jev-1.13.0) over an alias like jev-latest."
                ),
            )

    def clean_api_key(self):
        api_key = self.cleaned_data["api_key"].strip()
        if not api_key and not self.has_key:
            raise ValidationError(gettext("Paste the API key from your TypeSafe account."))
        return api_key

    def clean_model(self):
        return self.cleaned_data["model"].strip()


class ApiTokenForm(forms.ModelForm):
    name = forms.CharField(
        label=_("Token name"),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("e.g. Claude Code on my laptop")}),
        max_length=100,
    )

    class Meta:
        model = ApiToken
        fields = ("name",)
