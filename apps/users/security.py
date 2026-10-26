from ninja.security import HttpBearer
from apps.users.auth import decode_jwt
from apps.users.models import TelegramUser


class TelegramJWTAuth(HttpBearer):
    def authenticate(self, request, token: str):
        print(f"DEBUG: Authenticating token... {token[:10]}...")
        try:
            telegram_id = decode_jwt(token)
            if telegram_id is None:
                print("DEBUG: JWT decode returned None")
                return None
            
            user = TelegramUser.objects.filter(pk=telegram_id).first()
            if not user:
                print(f"DEBUG: User {telegram_id} not found in DB")
                return None
                
            print(f"DEBUG: Authenticated user {user.telegram_id}")
            return user
        except Exception as e:
            print(f"DEBUG: Auth exception: {str(e)}")
            return None
