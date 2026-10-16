from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse as r
from django.utils.text import slugify
from django.utils.translation import gettext
from django.views import View

from parsifal.apps.core.exceptions import DomainError
from parsifal.apps.reviews.decorators import main_author_required
from parsifal.apps.reviews.mixins import MainAuthorRequiredMixin, ReviewMixin
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.services import reviews as review_services
from parsifal.apps.reviews.settings.forms import ReviewSettingsForm


@main_author_required
@login_required
def settings(request, username, review_name):
    review = Review.objects.get(name=review_name, author__username__iexact=username)
    if request.method == "POST":
        form = ReviewSettingsForm(request.POST, instance=review)
        if form.is_valid():
            name = slugify(form.instance.name)
            unique_name = name
            if unique_name != review_name:
                i = 0
                while Review.objects.filter(name=unique_name, author__username=review.author.username):
                    i = i + 1
                    unique_name = "{0}-{1}".format(name, i)
            form.instance.name = unique_name
            review = form.save()
            messages.success(request, "Review was saved successfully.")
            return redirect(r("settings", args=(review.author.username, unique_name)))
    else:
        form = ReviewSettingsForm(instance=review)
    return render(request, "settings/review_settings.html", {"review": review, "form": form})


class DeleteReviewView(LoginRequiredMixin, MainAuthorRequiredMixin, ReviewMixin, View):
    @transaction.atomic()
    def post(self, request, *args, **kwargs):
        sources = self.review.sources.all()
        for source in sources:
            if not source.is_default:
                self.review.sources.remove(source)
                source.delete()
        self.review.delete()
        messages.success(request, gettext("The review was deleted with success."))
        return redirect(request.user)


class ManageAccessView(LoginRequiredMixin, MainAuthorRequiredMixin, ReviewMixin, View):
    """Co-authors of a review: the main author adds existing accounts by username and removes them."""

    template_name = "settings/manage_access.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {"review": self.review})

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        try:
            if action == "add":
                user = review_services.find_user(username=request.POST.get("username", "").strip())
                review_services.add_co_author(review=self.review, user=user)
                messages.success(request, gettext("%(user)s is now a co-author.") % {"user": user.username})
            elif action == "remove":
                user = review_services.find_user_by_id(request.POST.get("user_id"))
                review_services.remove_co_author(review=self.review, user=user)
                messages.success(request, gettext("%(user)s was removed from the review.") % {"user": user.username})
        except DomainError as error:
            messages.error(request, str(error))
        return redirect("manage_access", self.review.author.username, self.review.name)
