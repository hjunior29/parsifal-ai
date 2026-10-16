from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError

from ninja import Router

from parsifal.api.deps import require_superuser
from parsifal.api.v1.schemas.accounts import MeOut, TokenCreatedOut, TokenCreateIn, TokenOut, UserCreateIn
from parsifal.api.v1.schemas.common import UserOut
from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.validators import ASCIIUsernameValidator, validate_forbidden_usernames
from parsifal.apps.core.exceptions import Conflict, NotFound, ValidationError

router = Router(tags=["account"])


@router.get("/me", response=MeOut, operation_id="me")
def me(request):
    user = request.auth
    return MeOut(
        id=user.pk,
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_superuser=user.is_superuser,
        active_tokens=user.api_tokens.active().count(),
    )


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


@router.delete("/tokens/{int:token_id}", response={204: None}, operation_id="tokens_revoke")
def tokens_revoke(request, token_id: int):
    try:
        token = request.auth.api_tokens.get(pk=token_id)
    except ApiToken.DoesNotExist:
        raise NotFound(f"Token {token_id} not found.")
    token.revoke()
    return 204, None
