"""
The user's integrations with third-party services (only Jev for now), shared by Settings → Integrations and the
JSON API. The API key is never returned, only ``Integration.masked_key``.
"""

from parsifal.apps.accounts.models import Integration
from parsifal.apps.core import jev
from parsifal.apps.core.exceptions import UpstreamError, ValidationError

API_KEY_LENGTH = Integration._meta.get_field("api_key").max_length
MODEL_LENGTH = Integration._meta.get_field("model").max_length


def get_jev(user):
    """The user's Jev integration, or None."""
    return Integration.objects.filter(user=user, provider=Integration.JEV).first()


def save_jev(user, *, api_key=None, model=None):
    """
    Create or update the user's Jev integration. A missing or blank ``api_key`` keeps the saved one (required the
    first time); a missing or blank ``model`` keeps the saved one (``jev.DEFAULT_MODEL`` the first time).
    """
    integration = get_jev(user) or Integration(user=user, provider=Integration.JEV, model=jev.DEFAULT_MODEL)
    api_key = (api_key or "").strip()
    model = (model or "").strip()
    if api_key:
        if len(api_key) > API_KEY_LENGTH:
            raise ValidationError(f"api_key must have at most {API_KEY_LENGTH} characters.", field="api_key")
        integration.api_key = api_key
    elif not integration.api_key:
        raise ValidationError("Paste the API key from your TypeSafe account.", field="api_key")
    if model:
        if len(model) > MODEL_LENGTH:
            raise ValidationError(f"model must have at most {MODEL_LENGTH} characters.", field="model")
        integration.model = model
    integration.save()
    return integration


def test_jev(user):
    """Ask Jev which models the saved key can use; raises when there is no key or Jev refuses or fails."""
    integration = get_jev(user)
    if integration is None:
        raise ValidationError("Save an API key first.", field="api_key")
    try:
        return jev.list_models(integration.api_key)
    except jev.JevError as error:
        if error.fatal:
            raise ValidationError(str(error), field="api_key")
        raise UpstreamError(str(error))


def remove_jev(user):
    """Delete the user's Jev integration; returns whether there was one."""
    deleted, _ = Integration.objects.filter(user=user, provider=Integration.JEV).delete()
    return bool(deleted)
