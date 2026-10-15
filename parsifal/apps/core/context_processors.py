from django.conf import settings as django_settings

import parsifal


def settings(request):
    return {
        "parsifal_version": parsifal.__version__,
        "parsifal_release": django_settings.PARSIFAL_RELEASE,
        "parsifal_environment": django_settings.PARSIFAL_ENVIRONMENT,
        "allow_signup": django_settings.PARSIFAL_ALLOW_SIGNUP,
    }
