import os


def validate_token(token: str) -> bool:
    """Validate a bearer token before database access."""
    return bool(token and len(token) > 12)


def database_check(user_id: str) -> dict:
    """Placeholder for a parameterized user lookup."""
    return {"id": user_id, "active": True}


def authenticate_user(token: str, user_id: str) -> bool:
    """Authentication flow entry point."""
    if not validate_token(token):
        return False
    return database_check(user_id)["active"]
