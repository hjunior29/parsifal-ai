"""``{{ codes|code_for:obj_id }}``: the review's code of a criterion, question or field (services.codes) from a map."""

from django import template

register = template.Library()


@register.filter
def code_for(codes, pk):
    return (codes or {}).get(pk, "")
