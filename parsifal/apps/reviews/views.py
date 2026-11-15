from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse as r
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from parsifal.apps.core.exceptions import DomainError
from parsifal.apps.reviews.conducting.views import _paginate
from parsifal.apps.reviews.decorators import author_required, main_author_required
from parsifal.apps.reviews.forms import CreateReviewForm, ReviewForm
from parsifal.apps.reviews.models import Review, ReviewEvent
from parsifal.apps.reviews.services import history, review_backups, reviews as review_services


@login_required
def reviews(request, username):
    """The current user's reviews. There are no public profiles on a self-hosted instance."""
    if username.lower() != request.user.username.lower():
        raise Http404
    user_reviews = request.user.profile.get_reviews()
    return render(request, "reviews/reviews.html", {"user_reviews": user_reviews, "page_user": request.user})


@login_required
def new(request):
    if request.method == "POST":
        form = CreateReviewForm(request.POST)
        if form.is_valid():
            form.instance.author = request.user

            name = slugify(form.instance.title)
            if not name:
                name = "literature-review"
            unique_name = name
            i = 0
            while Review.objects.filter(name=unique_name, author__username=request.user.username):
                i = i + 1
                unique_name = "{0}-{1}".format(name, i)
            form.instance.name = unique_name
            review = form.save()
            review_services.record_created(review, request.user)
            messages.success(request, "Review created successfully.")
            return redirect(r("review", args=(review.author.username, review.name)))
    else:
        form = CreateReviewForm()
    return render(request, "reviews/new.html", {"form": form})


@login_required
@require_POST
def import_review(request):
    """A new review from a review backup (downloaded from Review settings → Backups, here or in another Parsifal)."""
    upload = request.FILES.get("file")
    if upload is None:
        messages.error(request, "Choose a review backup file.")
        return redirect(r("reviews:new"))
    try:
        review = review_backups.import_review(actor=request.user, content=upload.read())
    except DomainError as error:
        messages.error(request, str(error))
        return redirect(r("reviews:new"))
    messages.success(request, "The review was imported from the backup.")
    return redirect(r("review", args=(review.author.username, review.name)))


@author_required
@login_required
def review(request, username, review_name):
    review = Review.objects.get(name=review_name, author__username__iexact=username)
    if request.method == "POST":
        tracker = review_services.track_review(review, "title", "description")
        form = ReviewForm(request.POST, instance=review)
        if form.is_valid():
            review = form.save()
            review_services.record_changes(review, tracker)
            messages.success(request, "Review was saved successfully.")
            return redirect(r("review", args=(review.author.username, review.name)))
    else:
        form = ReviewForm(instance=review)
    return render(request, "reviews/review.html", {"review": review, "form": form})


@main_author_required
@login_required
@require_POST
def remove_author_from_review(request):
    try:
        author_id = request.POST.get("user-id")
        review_id = request.POST.get("review-id")
        author = User.objects.get(pk=author_id)
        review = Review.objects.get(pk=review_id)
        review.co_authors.remove(author)
        review.save()
        name = author.get_full_name() or author.username
        history.record(
            review,
            ReviewEvent.REVIEW,
            history.REMOVED,
            f"Removed the co-author {history.quote(name)}",
            subject="co_author",
            subject_id=author.pk,
        )
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def save_description(request):
    try:
        review_id = request.POST["review-id"]
        description = request.POST["description"]
        review = Review.objects.get(pk=review_id)
        if len(description) > 500:
            return HttpResponseBadRequest(
                "The review description should not exceed 500 characters. The given description have %s characters."
                % len(description)
            )
        else:
            tracker = review_services.track_review(review, "description")
            review.description = description
            review.save()
            review_services.record_changes(review, tracker)
            return HttpResponse("Your review has been saved successfully!")
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def leave(request):
    review_id = request.POST.get("review-id")
    review = get_object_or_404(Review, pk=review_id)
    review.co_authors.remove(request.user)
    review.save()
    history.record(review, ReviewEvent.REVIEW, history.REMOVED, "Left the review", subject="co_author")
    messages.add_message(request, messages.SUCCESS, "You successfully left the review {0}.".format(review.title))
    return redirect("/" + request.user.username + "/")


# The filters of the History (query string → services.history.list_events).
HISTORY_FILTERS = ("area", "action", "actor", "via", "since", "until", "q", "study", "amendments")


@author_required
@login_required
def review_history(request, username, review_name):
    """
    The History: every change to the review, the newest first, a page at a time, with filters (``HISTORY_FILTERS``).
    ``study`` keeps the changes to one study.
    """
    review = request.review
    filters = {key: request.GET.get(key, "").strip() for key in HISTORY_FILTERS}
    study = None
    if filters["study"].isdigit():
        study = review.article_set.filter(pk=filters["study"]).only("id", "title").first()
    if study is None:
        filters["study"] = ""
    try:
        events = history.list_events(
            review,
            area=filters["area"],
            action=filters["action"],
            actor=filters["actor"],
            via=filters["via"],
            article_id=study.pk if study else None,
            since=filters["since"],
            until=filters["until"],
            query=filters["q"],
            amendments=True if filters["amendments"] else None,
        )
        error = ""
    except DomainError as problem:
        events, error = review.events.none(), str(problem)
    context = _paginate(request, events, "history_per_page")
    page_events = list(context["page"])
    studies = {event.pk: history.event_studies(event) for event in page_events if event.study_count}
    for event in page_events:
        event.studies = studies.get(event.pk, ())
    query = request.GET.copy()
    for key in ("page", "per-page"):  # the size is kept in the session
        query.pop(key, None)
    every_study = query.copy()
    every_study.pop("study", None)
    context.update(
        review=review,
        events=page_events,
        filters=filters,
        study=study,
        error=error,
        query=query.urlencode(),
        every_study_query=every_study.urlencode(),
        filtered=any(filters.values()),
        areas=ReviewEvent.AREAS,
        actions=ReviewEvent.ACTIONS,
        vias=ReviewEvent.VIA,
        actors=history.actors(review),
        agents=set(review.agents.values_list("user_id", flat=True)),
    )
    return render(request, "reviews/history.html", context)
