from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy as _

from parsifal.apps.reviews.models import Review


class Profile(models.Model):
    SYSTEM, LIGHT, DARK = "system", "light", "dark"
    THEMES = (
        (SYSTEM, _("The system's (light or dark, as the device is set)")),
        (LIGHT, _("Light")),
        (DARK, _("Dark")),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("user"))
    # The columns of the study list on Study Selection, in order (services/study_columns.py); empty: the default.
    study_columns = models.JSONField(_("columns of the study list"), default=list, blank=True)
    theme = models.CharField(_("theme"), max_length=6, choices=THEMES, default=SYSTEM)

    class Meta:
        verbose_name = _("profile")
        verbose_name_plural = _("profiles")
        db_table = "auth_profile"

    def __str__(self):
        return self.get_screen_name()

    def get_screen_name(self):
        try:
            if self.user.get_full_name():
                return self.user.get_full_name()
            else:
                return self.user.username
        except Exception:
            return self.user.username

    def get_reviews(self):
        user_reviews = []
        author_reviews = Review.objects.select_related("author__profile").filter(author=self.user)
        co_author_reviews = Review.objects.select_related("author__profile").filter(co_authors=self.user)
        for r in author_reviews:
            user_reviews.append(r)
        for r in co_author_reviews:
            user_reviews.append(r)
        user_reviews.sort(key=lambda r: r.last_update, reverse=True)
        return user_reviews


def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


def save_user_profile(sender, instance, **kwargs):
    """Every user has a profile. It is not saved again with the user: a copy held by the user would undo changes."""
    Profile.objects.get_or_create(user=instance)


post_save.connect(create_user_profile, sender=User)
post_save.connect(save_user_profile, sender=User)
