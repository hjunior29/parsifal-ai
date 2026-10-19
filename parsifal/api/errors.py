from parsifal.apps.core.exceptions import (
    Conflict,
    DomainError,
    NotFound,
    PermissionDenied,
    UpstreamError,
    ValidationError,
)

STATUS_CODES = (
    (NotFound, 404),
    (PermissionDenied, 403),
    (Conflict, 409),
    (ValidationError, 422),
    (UpstreamError, 502),
    (DomainError, 400),
)


def status_for(error):
    for klass, status in STATUS_CODES:
        if isinstance(error, klass):
            return status
    return 400


def register(api):
    @api.exception_handler(DomainError)
    def domain_error(request, error):
        payload = {"detail": str(error), "code": error.code}
        if error.field:
            payload["field"] = error.field
        return api.create_response(request, payload, status=status_for(error))
