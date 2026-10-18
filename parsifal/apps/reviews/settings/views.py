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
from parsifal.apps.reviews.services import agents as agent_services
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
    """
    Who works on the review: the main author and the AI agents it created as co-authors. An agent is an account of
    its own for this review, with its own API token; deleting it deletes the account and what it recorded.
    """

    template_name = "settings/manage_access.html"

    def _render(self, request, new_token=None, new_token_agent=None):
        agents = [
            {"agent": agent, "stats": agent_services.stats(agent)} for agent in agent_services.list_agents(self.review)
        ]
        agent_user_ids = {row["agent"].user_id for row in agents}
        context = {
            "review": self.review,
            "agents": agents,
            "other_co_authors": [user for user in self.review.co_authors.all() if user.pk not in agent_user_ids],
            "new_token": new_token,
            "new_token_agent": new_token_agent,
            "deletion_warning": agent_services.DELETION_WARNING,
        }
        return render(request, self.template_name, context)

    def get(self, request, *args, **kwargs):
        return self._render(request)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        try:
            if action == "create_agent":
                created = agent_services.create_agent(
                    review=self.review, actor=request.user, name=request.POST.get("name", "")
                )
                # Rendered, not redirected: the token is shown exactly once and never stored.
                return self._render(request, created.raw_key, created.agent)
            if action == "new_token":
                created = agent_services.new_token(
                    review=self.review, actor=request.user, agent_id=request.POST.get("user_id")
                )
                return self._render(request, created.raw_key, created.agent)
            if action == "delete_agent":
                agent = agent_services.get_agent(self.review, request.POST.get("user_id"))
                name = agent.name
                agent_services.delete_agent(review=self.review, actor=request.user, agent_id=agent.user_id)
                messages.success(
                    request, gettext("Agent %(name)s and everything it recorded were deleted.") % {"name": name}
                )
        except DomainError as error:
            messages.error(request, str(error))
        return redirect("manage_access", self.review.author.username, self.review.name)
