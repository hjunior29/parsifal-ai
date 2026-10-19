"""
Minimal HTTP client for Jev, TypeSafe's typed decision model (the "System One" API). Parsifal only evaluates
questions against a state (``POST /v1/systemone``) and lists the models a key can use (``GET /v1/models``).

The base URL comes from the ``JEV_API_URL`` setting, so a compatible server can stand in for TypeSafe's. Errors never
carry the API key.
"""

import time

from django.conf import settings

import requests

DEFAULT_MODEL = "jev-1.13.0"
TIMEOUT = 30  # seconds per HTTP request
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}  # rate limited, overloaded or a transient server error
RETRY_DELAYS = (1, 2, 4)  # seconds; Retry-After wins when present, capped at MAX_RETRY_AFTER
MAX_RETRY_AFTER = 10


class JevError(Exception):
    """A request to Jev failed. ``fatal`` means retrying cannot help (the key was rejected)."""

    def __init__(self, message, *, status=None, fatal=False):
        super().__init__(message)
        self.status = status
        self.fatal = fatal


def base_url():
    return getattr(settings, "JEV_API_URL", "https://api.typesafe.ai").rstrip("/")


def _retry_after(response, default):
    try:
        return min(max(float(response.headers.get("Retry-After", default)), 0), MAX_RETRY_AFTER)
    except (TypeError, ValueError):
        return default


def _detail(response):
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or response.reason
    if isinstance(body, dict):
        for key in ("message", "detail", "error"):
            if isinstance(body.get(key), str):
                return body[key][:200]
    return str(body)[:200]


def _request(method, path, api_key, *, json=None, sleep=time.sleep):
    url = f"{base_url()}{path}"
    headers = {"Authorization": f"Bearer {api_key}"}
    delays = list(RETRY_DELAYS)
    while True:
        try:
            response = requests.request(method, url, headers=headers, json=json, timeout=TIMEOUT)
        except requests.RequestException as error:
            if not delays:
                raise JevError(f"Could not reach Jev ({error.__class__.__name__}).")
            sleep(delays.pop(0))
            continue
        if response.status_code in RETRY_STATUSES and delays:
            sleep(_retry_after(response, delays.pop(0)))
            continue
        break
    if response.status_code in (401, 403):
        raise JevError(
            "Jev rejected the API key. Update it in Settings → Integrations.", status=response.status_code, fatal=True
        )
    if response.status_code >= 400:
        raise JevError(f"Jev answered {response.status_code}: {_detail(response)}", status=response.status_code)
    try:
        return response.json()
    except ValueError:
        raise JevError("Jev returned a response that is not JSON.", status=response.status_code)


def evaluate(api_key, *, model, state, questions, sleep=time.sleep):
    """Ask ``questions`` about ``state``; returns the decoded response (``model``, ``answers``, ``usage``)."""
    payload = _request(
        "POST", "/v1/systemone", api_key, json={"model": model, "state": state, "questions": questions}, sleep=sleep
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise JevError("Jev returned a response without answers.")
    return payload


def list_models(api_key, *, sleep=time.sleep):
    """
    The models the key can use, as ``{"name", "description", "release_date"}`` in Jev's order (also a cheap way to
    check that the key works). ``GET /v1/models`` answers a list of model cards; wrapped lists are accepted too.
    """
    payload = _request("GET", "/v1/models", api_key, sleep=sleep)
    items = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
    models = []
    for item in items if isinstance(items, list) else []:
        card = item if isinstance(item, dict) else {"name": item}
        name = card.get("name") or card.get("id")
        if isinstance(name, str) and name:
            models.append(
                {
                    "name": name,
                    "description": str(card.get("description") or ""),
                    "release_date": str(card.get("release_date") or ""),
                }
            )
    return models
