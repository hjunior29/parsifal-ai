from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.urls import reverse as r
from django.utils.text import slugify
from django.utils.translation import gettext
from django.views import View

from parsifal.apps.core.exceptions import DomainError
from parsifal.apps.core.models import files_are_local, files_storage
from parsifal.apps.reviews.decorators import main_author_required
from parsifal.apps.reviews.mixins import MainAuthorRequiredMixin, ReviewMixin
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.services import agents as agent_services, review_backups, selection
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
    context = {"review": review, "form": form, "reset": selection.reset_summary(review)}
    return render(request, "settings/review_settings.html", context)


class ResetSelectionView(LoginRequiredMixin, MainAuthorRequiredMixin, ReviewMixin, View):
    """Danger zone: back to the start of study selection, deleting the decisions of the reviewers checked."""

    def post(self, request, *args, **kwargs):
        try:
            done = selection.reset(
                review=self.review, actor=request.user, reviewer_ids=request.POST.getlist("reviewer_ids")
            )
        except DomainError as error:
            messages.error(request, str(error))
            return redirect("settings", self.review.author.username, self.review.name)
        unclassified, deleted = done["unclassified"], done["decisions_deleted"]
        message = f"The study selection was reset: {unclassified} stud{'y is' if unclassified == 1 else 'ies are'} "
        message += "unclassified again"
        if deleted:
            message += f", {deleted} decision{'' if deleted == 1 else 's'} deleted"
        if done["runs_discarded"]:
            message += ", the AI screening run in progress was discarded"
        messages.success(request, message + ".")
        return redirect("study_selection", self.review.author.username, self.review.name)


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


class ReviewBackupsView(LoginRequiredMixin, MainAuthorRequiredMixin, ReviewMixin, View):
    """
    The review's backups kept on the server: back it up now, add a backup file, download one, restore one over the
    review (what it has now is backed up first) or delete one.
    """

    template_name = "settings/review_backups.html"

    def get(self, request, *args, **kwargs):
        context = {
            "review": self.review,
            "backups": review_backups.list_backups(self.review, request.user),
            "keep": review_backups.keep(),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        try:
            if action == "create":
                review_backups.create_backup(review=self.review, actor=request.user)
                messages.success(request, gettext("The review was backed up."))
            elif action == "upload":
                upload = request.FILES.get("file")
                if upload is None:
                    raise DomainError(gettext("Choose a backup file."))
                review_backups.upload_backup(
                    review=self.review, actor=request.user, filename=upload.name, content=upload.read()
                )
                messages.success(request, gettext("The backup file was added to the list."))
            elif action == "restore":
                review_backups.restore_backup(
                    review=self.review, actor=request.user, backup_id=request.POST.get("backup_id")
                )
                messages.success(
                    request, gettext("The review was restored. What it had before is the first backup of the list.")
                )
            elif action == "delete":
                review_backups.delete_backup(
                    review=self.review, actor=request.user, backup_id=request.POST.get("backup_id")
                )
                messages.success(request, gettext("The backup was deleted."))
        except DomainError as error:
            messages.error(request, str(error))
        return redirect("review_backups", self.review.author.username, self.review.name)


class DownloadReviewBackupView(LoginRequiredMixin, MainAuthorRequiredMixin, ReviewMixin, View):
    def get(self, request, *args, **kwargs):
        try:
            backup = review_backups.get_backup(self.review, request.user, kwargs["backup_id"])
        except DomainError:
            return redirect("review_backups", self.review.author.username, self.review.name)
        if files_are_local():
            return FileResponse(backup.file.open(), as_attachment=True, filename=backup.file.filename)
        return redirect(files_storage().url(backup.file.key))
