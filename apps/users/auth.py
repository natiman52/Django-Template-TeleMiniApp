import hmac
import hashlib
import json
import time
import jwt
from urllib.parse import parse_qs, unquote
from django.conf import settings


def validate_telegram_init_data(init_data: str) -> dict | None:
    """
    Validates the data received from the Telegram WebApp.
    Returns the user data if valid, None otherwise.
    """
    
    if not init_data:
        return None

    # For local development with a debug bypass
    if settings.DEBUG and 'hash=debug' in init_data:
        # Mock data for testing
        return {
            'id': 12345678,
            'first_name': 'Test',
            'last_name': 'User',
            'username': 'testuser',
        }

    try:
        parsed_data = parse_qs(init_data)
        if 'hash' not in parsed_data:
            return None
        received_hash = parsed_data.pop('hash')[0]
        # Sort keys alphabetically
        data_check_list = []
        for key in sorted(parsed_data.keys()):
            data_check_list.append(f"{key}={parsed_data[key][0]}")
        
        data_check_string = "\n".join(data_check_list)
        
        # 1. Derive secret key from Bot Token
        secret_key = hmac.new(
            b'WebAppData',
            settings.TELEGRAM_BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        # 2. Compute HMAC of the data check string
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
            
        user_str = parsed_data.get('user', [None])[0]
        if not user_str:
            return None
            
        return json.loads(unquote(user_str))
        
    except Exception as e:
        print(f"InitData Validation Error: {str(e)}")
        return None


def create_jwt(telegram_id: int) -> str:
    """Create a JWT access token for a TelegramUser."""
    payload = {
        'sub': str(telegram_id),
        'iat': int(time.time()),
        'exp': int(time.time()) + 60 * 60 * 24,  # 24 hours
    }
    # Ensure key is bytes for some jwt versions
    key = settings.SECRET_KEY
    print(f"DEBUG: Creating JWT with key starting: {key[:5]}...")
    token = jwt.encode(payload, key, algorithm='HS256')
    if isinstance(token, bytes):
        return token.decode('utf-8')
    return token


def decode_jwt(token: str) -> int | None:
    """Decode a JWT and return the telegram_id, or None if invalid."""
    try:
        key = settings.SECRET_KEY
        print(f"DEBUG: Decoding JWT with key starting: {key[:5]}...")
        payload = jwt.decode(token, key, algorithms=['HS256'])
        return int(payload['sub'])
    except jwt.ExpiredSignatureError:
        print("JWT Error: Token expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"JWT Error: Invalid token: {str(e)}")
        return None
    except (KeyError, ValueError) as e:
        print(f"JWT Error: Payload error: {str(e)}")
        return None
    except Exception as e:
        print(f"JWT Error: Unexpected error: {str(e)}")
        return None
