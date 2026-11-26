from django.http import Http404
from django.shortcuts import render
from django.utils.safestring import mark_safe

from parsifal.apps.docs import pages


def page(request, slug="index"):
    try:
        current = pages.BY_SLUG[slug]
    except KeyError:
        raise Http404
    idx = pages.PAGES.index(current)
    prev_page = pages.PAGES[idx - 1] if idx > 0 else None
    next_page = pages.PAGES[idx + 1] if idx + 1 < len(pages.PAGES) else None
    return render(
        request,
        "docs/page.html",
        {
            "page": current,
            "sections": pages.sections(),
            "prev_page": prev_page,
            "next_page": next_page,
            "content": mark_safe(pages.render_page(current)),  # our own Markdown files, not user input
        },
    )
