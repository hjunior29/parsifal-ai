from ninja.security import HttpBearer, django_auth

from parsifal.apps.accounts.models import ApiToken


class BearerTokenAuth(HttpBearer):
    """``Authorization: Bearer pfl_...`` — resolves to the token's user, who becomes ``request.auth``."""

    def authenticate(self, request, token):
        user = ApiToken.objects.authenticate(token)
        if user is None:
            return None
        request.user = user
        return user


# Session cookies keep working for the browser (with CSRF); tokens are for scripts and agents.
API_AUTH = [BearerTokenAuth(), django_auth]
