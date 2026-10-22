"""
Minimal HTTP client for Jev, TypeSafe's typed decision model (the "System One" API). Parsifal only evaluates
questions against a state (``POST /v1/systemone``) and lists the models a key can use (``GET /v1/models``).

The base URL comes from the ``JEV_API_URL`` setting, so a compatible server can stand in for TypeSafe's. Errors never
carry the API key.

Requests made with the same key are spaced so that, however many threads send them, they stay under Jev's rate limit
(``JEV_REQUESTS_PER_MINUTE``, 1,080 by default, 90% of TypeSafe's 1,200; 0 turns the spacing off). When Jev answers
429 every request with that key waits, not only the one refused.
"""

import hashlib
import threading
import time

from django.conf import settings

import requests

DEFAULT_MODEL = "jev-1.13.0"
TIMEOUT = 30  # seconds per HTTP request
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}  # rate limited, overloaded or a transient server error
RETRY_DELAYS = (1, 2, 4)  # seconds; Retry-After wins when present, capped at MAX_RETRY_AFTER
MAX_RETRY_AFTER = 10
QUICK_TIMEOUT = 5  # seconds, for lookups made while a page loads (one try, no retries)
DEFAULT_REQUESTS_PER_MINUTE = 1080

_now = time.monotonic
_turns = {}  # SHA-256 of a key -> the earliest moment its next request may leave
_turns_lock = threading.Lock()


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


def _spacing():
    """Seconds between two requests with the same key; 0 when the spacing is off."""
    rate = getattr(settings, "JEV_REQUESTS_PER_MINUTE", DEFAULT_REQUESTS_PER_MINUTE)
    return 60.0 / rate if rate and rate > 0 else 0.0


def _key_id(api_key):
    return hashlib.sha256(api_key.encode()).hexdigest()  # the key itself is never kept


def _wait_turn(api_key, sleep):
    """Wait until a request with this key may leave, and book the next turn."""
    spacing = _spacing()
    if not spacing:
        return
    key = _key_id(api_key)
    with _turns_lock:
        now = _now()
        turn = max(now, _turns.get(key, 0.0))
        _turns[key] = turn + spacing
    if turn > now:
        sleep(turn - now)


def _hold(api_key, seconds):
    """Jev asked to slow down: no request with this key leaves for ``seconds``, from any thread."""
    if not _spacing():
        return
    key = _key_id(api_key)
    with _turns_lock:
        _turns[key] = max(_turns.get(key, 0.0), _now() + seconds)


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


def _request(method, path, api_key, *, json=None, sleep=time.sleep, quick=False):
    url = f"{base_url()}{path}"
    headers = {"Authorization": f"Bearer {api_key}"}
    delays = [] if quick else list(RETRY_DELAYS)
    timeout = QUICK_TIMEOUT if quick else TIMEOUT
    while True:
        if not quick:
            _wait_turn(api_key, sleep)
        try:
            response = requests.request(method, url, headers=headers, json=json, timeout=timeout)
        except requests.RequestException as error:
            if not delays:
                raise JevError(f"Could not reach Jev ({error.__class__.__name__}).")
            sleep(delays.pop(0))
            continue
        if response.status_code in RETRY_STATUSES and delays:
            delay = _retry_after(response, delays.pop(0))
            if response.status_code == 429:
                _hold(api_key, delay)
            sleep(delay)
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


def list_models(api_key, *, sleep=time.sleep, quick=False):
    """
    The models the key can use, as ``{"name", "description", "release_date"}`` in Jev's order (also a cheap way to
    check that the key works). ``GET /v1/models`` answers a list of model cards; wrapped lists are accepted too.
    ``quick``: one try with a short timeout, for pages that ask while loading.
    """
    payload = _request("GET", "/v1/models", api_key, sleep=sleep, quick=quick)
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
