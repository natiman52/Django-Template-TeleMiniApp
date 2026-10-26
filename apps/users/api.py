from ninja import Router, Schema
from apps.users.auth import validate_telegram_init_data, create_jwt
from apps.users.models import TelegramUser
from apps.users.security import TelegramJWTAuth
from ninja.errors import HttpError
import urllib.parse

router = Router(tags=["Auth & Users"])
auth = TelegramJWTAuth()


class TelegramAuthIn(Schema):
    init_data: str


class AuthOut(Schema):
    token: str
    user_id: int
    username: str | None
    first_name: str
    guided : bool
    is_verified: bool
    admin: bool


class UserProfileOut(Schema):
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str
    photo_url: str | None
    phone_number: str | None
    is_verified: bool
    is_premium: bool = False
    earned_balance: float
    ad_wallet: float
    hold_balance: float
    notifications_enabled: bool
    guided: bool
    admin: bool


class UpdatePhoneIn(Schema):
    phone_number: str


class UpdateGuidedIn(Schema):
    guided: bool


class UpdateNotificationsIn(Schema):
    notifications_enabled: bool




def get_start_param_from_init_data(init_data: str) -> str | None:
    """Extract start_param from signed Telegram WebApp initData."""
    if not init_data:
        return None
    parsed = urllib.parse.parse_qs(init_data)
    value = parsed.get('start_param', [None])[0]
    return value or None


@router.post("/auth/telegram", response=AuthOut, auth=None)
def telegram_auth(request, payload: TelegramAuthIn):
    """
    Validates Telegram WebApp initData, creates or updates the user,
    and returns a JWT token.
    """
    user_data = validate_telegram_init_data(payload.init_data)
    if user_data is None:
        raise HttpError(401, "Invalid Telegram initData")

    telegram_id = user_data['id']
    user_exists = TelegramUser.objects.filter(telegram_id=telegram_id).exists()

    user, created = TelegramUser.objects.update_or_create(
        telegram_id=telegram_id,
        defaults={
            'username': user_data.get('username'),
            'first_name': user_data.get('first_name', ''),
            'last_name': user_data.get('last_name', ''),
            'photo_url': user_data.get('photo_url'),
            'is_premium': user_data.get('is_premium', False),
        }
    )

    if created or not user_exists:
        start_param = get_start_param_from_init_data(payload.init_data)
        # if the start params fit do something

    token = create_jwt(user.telegram_id)
    return AuthOut(
        token=token,
        user_id=user.telegram_id,
        username=user.username,
        guided=user.guided,
        first_name=user.first_name,
        is_verified=user.is_verified,
        admin=user.admin,
    )


@router.get("/users/me", response=UserProfileOut, auth=auth)
def get_my_profile(request):
    """Returns the current authenticated user's profile."""
    user: TelegramUser = request.auth
    return UserProfileOut(
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        photo_url=user.photo_url,
        phone_number=user.phone_number,
        guided=user.guided,
        is_verified=user.is_verified,
        is_premium=user.is_premium,
        earned_balance=float(user.earned_balance),
        ad_wallet=float(user.ad_wallet),
        hold_balance=float(user.hold_balance),
        notifications_enabled=user.notifications_enabled,
        admin=user.admin,
    )


@router.patch("/users/me/phone", response=UserProfileOut, auth=auth)
def update_phone(request, payload: UpdatePhoneIn):
    """Updates the user's cellphone number, making them verification-ready."""
    user: TelegramUser = request.auth
    user.phone_number = payload.phone_number
    user.save()
    return get_my_profile(request)


@router.patch("/users/me/notifications", response=UserProfileOut, auth=auth)
def update_notifications(request, payload: UpdateNotificationsIn):
    """Toggles bot notification preference for the authenticated user."""
    user: TelegramUser = request.auth
    user.notifications_enabled = payload.notifications_enabled
    user.save(update_fields=['notifications_enabled'])
    return get_my_profile(request)


