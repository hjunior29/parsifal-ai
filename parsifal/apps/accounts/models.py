import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from parsifal.apps.core import crypto

TOKEN_PREFIX = "pfl_"


class ApiTokenManager(models.Manager):
    def active(self):
        return self.filter(revoked_at__isnull=True)

    def authenticate(self, raw_token):
        """Return the user owning an active token, or None. Updates last_used_at."""
        if not raw_token or not raw_token.startswith(TOKEN_PREFIX):
            return None
        try:
            token = self.active().select_related("user").get(key_hash=ApiToken.hash_key(raw_token))
        except ApiToken.DoesNotExist:
            return None
        if not token.user.is_active:
            return None
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token.user


class ApiToken(models.Model):
    """
    Personal access token for the JSON API. Only a SHA-256 hash of the token is stored; the raw value is shown
    once, at creation time. The API acts as the token's user, so the usual author/co-author rules apply.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens", verbose_name=_("user")
    )
    name = models.CharField(_("name"), max_length=100, help_text=_("What this token is used for, e.g. 'Claude Code'."))
    prefix = models.CharField(_("prefix"), max_length=12, editable=False)
    key_hash = models.CharField(_("key hash"), max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    last_used_at = models.DateTimeField(_("last used at"), null=True, blank=True, editable=False)
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)

    objects = ApiTokenManager()

    class Meta:
        verbose_name = _("API token")
        verbose_name_plural = _("API tokens")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def generate_key():
        return TOKEN_PREFIX + secrets.token_urlsafe(30)

    @staticmethod
    def hash_key(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def create_for(cls, user, name):
        """Create a token and return ``(token, raw_key)``; ``raw_key`` is never recoverable afterwards."""
        raw_key = cls.generate_key()
        token = cls.objects.create(user=user, name=name, prefix=raw_key[:12], key_hash=cls.hash_key(raw_key))
        return token, raw_key

    @property
    def is_active(self):
        return self.revoked_at is None

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class Integration(models.Model):
    """
    A third-party service the user connected, with the API key Parsifal uses to call it on the user's behalf. Only
    Jev (TypeSafe), used by the AI exclusion screening, for now. The key is stored encrypted (``core.crypto``, derived
    from SECRET_KEY) because it has to be sent to the service; the pages show only its last characters and the API
    never returns it.
    """

    JEV = "jev"
    PROVIDERS = ((JEV, "Jev (TypeSafe)"),)
    API_KEY_LENGTH = 500

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="integrations", verbose_name=_("user")
    )
    provider = models.CharField(_("provider"), max_length=20, choices=PROVIDERS)
    api_key_encrypted = models.TextField(_("API key (encrypted)"))
    key_hint = models.CharField(_("last characters of the API key"), max_length=4, blank=True)
    model = models.CharField(_("default model"), max_length=100)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("integration")
        verbose_name_plural = _("integrations")
        constraints = (models.UniqueConstraint(fields=("user", "provider"), name="unique_integration_per_user"),)

    def __str__(self):
        return f"{self.get_provider_display()} ({self.user})"

    @property
    def api_key(self):
        """The decrypted key; raises ``crypto.DecryptionError`` if SECRET_KEY changed since it was saved."""
        return crypto.decrypt(self.api_key_encrypted)

    @api_key.setter
    def api_key(self, value):
        self.api_key_encrypted = crypto.encrypt(value)
        self.key_hint = value[-4:] if len(value) > 8 else ""

    @property
    def masked_key(self):
        return f"…{self.key_hint}"


class LibraryAccess(models.Model):
    """
    The user's library proxy, such as the access CAPES gives their institution to the publishers in the Portal de
    Periódicos (``ezNN.periodicos.capes.gov.br``). With it, the study window links each study through the proxy
    (``core.library_proxy``), so the publisher's page opens with the access the user's sign-in gives them. Only the
    proxy's address is kept: the sign-in (CAFe) and its session stay in the user's browser.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="library_access", verbose_name=_("user")
    )
    proxy = models.CharField(_("proxy address"), max_length=253)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("library access")
        verbose_name_plural = _("library access")

    def __str__(self):
        return f"{self.proxy} ({self.user})"
