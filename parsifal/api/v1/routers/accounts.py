from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import IntegrityError

from ninja import Router

from parsifal.api.deps import require_superuser
from parsifal.api.v1.schemas.accounts import (
    LibraryAccessIn,
    LibraryAccessOut,
    MeOut,
    MeUpdateIn,
    TokenCreatedOut,
    TokenCreateIn,
    TokenOut,
    UserCreateIn,
)
from parsifal.api.v1.schemas.common import UserOut
from parsifal.apps.accounts import services as integrations
from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.models import Profile
from parsifal.apps.authentication.validators import ASCIIUsernameValidator, validate_forbidden_usernames
from parsifal.apps.core import library_proxy
from parsifal.apps.core.exceptions import Conflict, NotFound, ValidationError
from parsifal.apps.reviews.services import study_columns

router = Router(tags=["account"])


def _me_out(user):
    return MeOut(
        id=user.pk,
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_superuser=user.is_superuser,
        active_tokens=user.api_tokens.active().count(),
        study_columns=study_columns.for_user(user),
        theme=user.profile.theme,
    )


@router.get("/me", response=MeOut, operation_id="me")
def me(request):
    return _me_out(request.auth)


@router.patch("/me", response=MeOut, operation_id="me_update")
def me_update(request, payload: MeUpdateIn):
    """
    Change your name, e-mail or theme (``theme``: system, light or dark; the same fields as Settings → Profile), or the
    columns of the study list on Study Selection (``study_columns``, in order: see ``me``; the web's Columns window).
    """
    user = request.auth
    fields = payload.dict(exclude_unset=True)
    if "study_columns" in fields:
        study_columns.save(user, fields.pop("study_columns") or [])
    if "theme" in fields:
        theme = fields.pop("theme")
        if theme not in dict(Profile.THEMES):
            raise ValidationError("theme must be system, light or dark.", field="theme")
        user.profile.theme = theme
        user.profile.save(update_fields=["theme"])
    for name, limit in (("first_name", 150), ("last_name", 150)):
        if name in fields:
            value = (fields[name] or "").strip()
            if len(value) > limit:
                raise ValidationError(f"{name} must have at most {limit} characters.", field=name)
            setattr(user, name, value)
    if "email" in fields:
        email = (fields["email"] or "").strip()
        if email:
            try:
                validate_email(email)
            except DjangoValidationError:
                raise ValidationError("Enter a valid e-mail address.", field="email")
            if get_user_model().objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                raise Conflict("A user with that email already exists.", field="email")
        user.email = email
    user.save(update_fields=["first_name", "last_name", "email"])
    return _me_out(user)


@router.get("/users", response=list[UserOut], operation_id="users_list")
def users_list(request):
    require_superuser(request)
    return get_user_model().objects.filter(is_active=True).order_by("username")


@router.post("/users", response={201: UserOut}, operation_id="users_create")
def users_create(request, payload: UserCreateIn):
    """Create an account (administrators only). Without a password the user must use the password reset flow."""
    require_superuser(request)
    User = get_user_model()
    if not payload.username.strip():
        raise ValidationError("username is required.", field="username")
    try:
        ASCIIUsernameValidator()(payload.username)
        validate_forbidden_usernames(payload.username)
    except DjangoValidationError as error:
        raise ValidationError(" ".join(error.messages), field="username")
    if User.objects.filter(username__iexact=payload.username).exists():
        raise Conflict("A user with that username already exists.", field="username")
    if payload.email and User.objects.filter(email__iexact=payload.email).exists():
        raise Conflict("A user with that email already exists.", field="email")
    try:
        user = User.objects.create_user(
            username=payload.username,
            email=payload.email,
            password=payload.password,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
    except IntegrityError:
        raise Conflict("A user with that username already exists.", field="username")
    return 201, user


@router.get("/tokens", response=list[TokenOut], operation_id="tokens_list")
def tokens_list(request):
    return request.auth.api_tokens.all()


@router.post("/tokens", response={201: TokenCreatedOut}, operation_id="tokens_create")
def tokens_create(request, payload: TokenCreateIn):
    if not payload.name.strip():
        raise ValidationError("name is required.", field="name")
    token, raw_key = ApiToken.create_for(request.auth, payload.name.strip()[:100])
    return 201, TokenCreatedOut(
        id=token.pk,
        name=token.name,
        prefix=token.prefix,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
        key=raw_key,
    )


def _own_token(request, token_id):
    try:
        return request.auth.api_tokens.get(pk=token_id)
    except ApiToken.DoesNotExist:
        raise NotFound(f"Token {token_id} not found.")


@router.post("/tokens/{int:token_id}/revoke", response={204: None}, operation_id="tokens_revoke")
def tokens_revoke(request, token_id: int):
    """Revoke one of your tokens: it stops working at once and stays listed as revoked."""
    _own_token(request, token_id).revoke()
    return 204, None


@router.delete("/tokens/{int:token_id}", response={204: None}, operation_id="tokens_delete")
def tokens_delete(request, token_id: int):
    """Delete a revoked token from the list for good (409 while it is still active: revoke it first)."""
    token = _own_token(request, token_id)
    if token.is_active:
        raise Conflict("Revoke the token before deleting it.")
    token.delete()
    return 204, None


def _library_access_out(access):
    if access is None:
        return LibraryAccessOut(configured=False)
    return LibraryAccessOut(
        configured=True, proxy=access.proxy, label=library_proxy.label(access.proxy), updated_at=access.updated_at
    )


@router.get("/integrations/library-access", response=LibraryAccessOut, operation_id="library_access_get")
def library_access_get(request):
    """
    Your library proxy (Settings → Library access), such as your institution's CAPES access: studies then carry an
    ``access_url`` that opens them through it, with the access your sign-in in the browser gives you.
    """
    return _library_access_out(integrations.get_library_access(request.auth))


@router.put("/integrations/library-access", response=LibraryAccessOut, operation_id="library_access_set")
def library_access_set(request, payload: LibraryAccessIn):
    """
    Save your library proxy from ``address``: the proxy's address (ezNN.periodicos.capes.gov.br) or that of any page
    opened through it (https://ieeexplore-ieee-org.ezNN.periodicos.capes.gov.br/document/1234567). Only the proxy's
    address is kept; Parsifal never signs in to CAPES. 422 when it is not a web address.
    """
    return _library_access_out(integrations.save_library_access(request.auth, address=payload.address))


@router.delete("/integrations/library-access", response={204: None}, operation_id="library_access_delete")
def library_access_delete(request):
    """Forget your library proxy: studies no longer carry an ``access_url``."""
    integrations.remove_library_access(request.auth)
    return 204, None
