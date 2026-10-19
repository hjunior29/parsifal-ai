"""
Typed errors raised by the service layer.

Views translate them into HTTP responses (messages or 4xx) and the JSON API maps them to status codes, so
services never need to know about requests.
"""


class DomainError(Exception):
    code = "domain_error"

    def __init__(self, message="", *, field=None):
        super().__init__(message)
        self.message = message
        self.field = field

    def __str__(self):
        return self.message or self.code


class NotFound(DomainError):
    code = "not_found"


class PermissionDenied(DomainError):
    code = "permission_denied"


class Conflict(DomainError):
    code = "conflict"


class ValidationError(DomainError):
    code = "validation_error"


class UpstreamError(DomainError):
    """A third-party service Parsifal depends on (e.g. Jev) failed or could not be reached."""

    code = "upstream_error"
