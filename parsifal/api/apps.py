from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ApiConfig(AppConfig):
    name = "parsifal.api"
    label = "parsifal_api"
    verbose_name = _("JSON API")
