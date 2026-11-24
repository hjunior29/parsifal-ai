"""``{% review_progress review as progress %}``: how far the review has come (services.progress)."""

from django import template

from parsifal.apps.reviews.services import progress

register = template.Library()


@register.simple_tag
def review_progress(review):
    return progress.progress(review)
