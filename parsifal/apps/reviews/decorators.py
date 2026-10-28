from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden

from parsifal.apps.reviews.models import Review


class AmbiguousReview(Exception):
    """The request names one review in its body and another in its query string."""


def request_review(request):
    """
    The review a request without the review in its URL acts on, named by ``review-id``: the body's for a POST, the
    query string's otherwise. A request naming two different reviews is refused: the permission check would see one
    and a view reading the other parameter would act on the other. Raises Http404 for an unknown review, KeyError
    when there is no ``review-id``.
    """
    posted = request.POST.get("review-id")
    queried = request.GET.get("review-id")
    if posted and queried and posted != queried:
        raise AmbiguousReview
    review_id = posted or queried
    if not review_id:
        raise KeyError("review-id")
    try:
        return Review.objects.get(pk=review_id)
    except (Review.DoesNotExist, ValueError, TypeError):
        raise Http404


def _review_guard(is_allowed):
    """
    A decorator that lets the request through when ``is_allowed(review, user)``. The review comes from the URL
    (username + review_name) or from ``review-id``; it is set as ``request.review`` for the view.
    """

    def decorator(f):
        def wrap(request, *args, **kwargs):
            if "review_name" in kwargs and "username" in kwargs:
                try:
                    review = Review.objects.get(
                        name=kwargs["review_name"], author__username__iexact=kwargs["username"]
                    )
                except Review.DoesNotExist:
                    raise Http404
                if not is_allowed(review, request.user):
                    raise Http404
            else:
                try:
                    review = request_review(request)
                except (KeyError, AmbiguousReview):
                    return HttpResponseBadRequest()
                if not is_allowed(review, request.user):
                    return HttpResponseForbidden()
            request.review = review
            return f(request, *args, **kwargs)

        wrap.__doc__ = f.__doc__
        wrap.__name__ = f.__name__
        return wrap

    return decorator


main_author_required = _review_guard(lambda review, user: review.author_id == user.id)
author_required = _review_guard(lambda review, user: review.is_author_or_coauthor(user))
