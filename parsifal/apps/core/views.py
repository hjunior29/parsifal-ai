from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.urls import reverse
from django.views.generic import RedirectView


def home(request):
    if request.user.is_authenticated:
        user_reviews = request.user.profile.get_reviews()
        return render(request, "core/home.html", {"user_reviews": user_reviews})
    return render(request, "core/cover.html")


class LoginRedirectView(LoginRequiredMixin, RedirectView):
    def get_redirect_url(self, *args, **kwargs):
        return reverse("reviews", kwargs={"username": self.request.user.username})
