from django.http import Http404
from django.shortcuts import render
from django.utils.safestring import mark_safe

from parsifal.apps.docs import pages


def page(request, slug="index"):
    try:
        current = pages.BY_SLUG[slug]
    except KeyError:
        raise Http404
    return render(
        request,
        "docs/page.html",
        {
            "page": current,
            "sections": pages.sections(),
            "content": mark_safe(pages.render_page(current)),  # our own Markdown files, not user input
        },
    )
