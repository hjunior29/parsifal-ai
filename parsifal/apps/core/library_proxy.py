"""
Links through a library proxy, such as the access CAPES gives each Brazilian institution to the publishers in the
Portal de Periódicos. Signed in through CAFe, the browser reaches a publisher at an address of the institution: the
publisher's own address with its dots turned into hyphens, followed by the proxy's address.

    https://ieeexplore.ieee.org/document/1234567
    https://ieeexplore-ieee-org.ezNN.periodicos.capes.gov.br/document/1234567

A DOI goes the same way (``doi.org`` → ``doi-org.ezNN.periodicos.capes.gov.br``), and doi.org then sends the browser
on to the publisher, still through the proxy. Parsifal only writes these addresses: the login, and the session that
gives access, stay in the user's browser. Opened without a session, the proxy asks the user to sign in first.

This is how EZproxy, the proxy CAPES and many libraries use, names the sites it serves over https ("HttpsHyphens").
"""

import re
from urllib.parse import urlsplit, urlunsplit

from parsifal.apps.core.exceptions import ValidationError

LENGTH = 253  # the longest host name
LABEL = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?")
CAPES = "periodicos.capes.gov.br"
# The portal itself, not an institution's access to the publishers.
CAPES_PORTAL = (CAPES, f"www.{CAPES}")
# The last part of a site's address, as it ends the first label of a page opened through the proxy.
GENERIC_ENDINGS = {"com", "org", "net", "edu", "gov", "int", "info", "io", "ai"}


def _error(message):
    return ValidationError(message, field="address")


def clean_host(value):
    """
    The proxy's address, from what the user pasted: the address itself (``ezNN.periodicos.capes.gov.br``, with or
    without ``https://``) or the address of any page opened through it, whose first part is that page's own site
    rewritten (``ieeexplore-ieee-org.ezNN.periodicos.capes.gov.br/document/1234567``).
    """
    text = (value or "").strip()
    if not text:
        raise _error("Paste the address of a study opened through CAPES, or the proxy's address.")
    if "://" not in text:
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        port, host = None, ""
    labels = host.split(".")
    if (
        parts.scheme.lower() not in ("http", "https")
        or port
        or len(labels) < 2
        or not all(LABEL.fullmatch(label) for label in labels)
    ):
        raise _error("That is not a web address. Paste the address of a study opened through CAPES.")
    # A page opened through the proxy: its first label is a site's address (ieeexplore-ieee-org), ending like one.
    site = labels[0].rsplit("-", 1)
    if len(labels) > 3 and len(site) == 2 and (site[1] in GENERIC_ENDINGS or len(site[1]) == 2):
        labels = labels[1:]
    host = ".".join(labels)
    if host in CAPES_PORTAL:
        raise _error(
            "That is the address of the CAPES portal itself. Signed in through CAFe, open a study at the publisher "
            f"and paste the address the browser shows: it has your institution's part, like ezNN.{CAPES}."
        )
    if len(host) > LENGTH:
        raise _error("That address is too long.")
    return host


def is_capes(host):
    return host == CAPES or host.endswith(f".{CAPES}")


def label(host):
    """The name of the link in the study window."""
    return "Via CAPES" if is_capes(host) else "Via proxy"


def proxied(url, host):
    """
    ``url`` through the proxy at ``host``, or None when it cannot be: not a web address, an address with a port, or
    a site whose address has hyphens of its own (how the proxy rewrites those is not documented, so no link rather
    than a wrong one). An address already through the proxy is returned as it is.
    """
    try:
        parts = urlsplit((url or "").strip())
        site = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not site:
        return None
    if site == host or site.endswith(f".{host}"):
        return url.strip()
    if port or "-" in site:
        return None
    return urlunsplit(("https", f"{site.replace('.', '-')}.{host}", parts.path or "/", parts.query, parts.fragment))
