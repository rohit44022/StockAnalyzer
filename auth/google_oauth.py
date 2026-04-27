"""
auth/google_oauth.py — Google Sign-In (Identity Services) integration.
═══════════════════════════════════════════════════════════════════════

Handles:
  - Server-side verification of Google ID tokens (JWT)
  - Auto-creation of users on first Google sign-in
  - Linking Google accounts to existing email-matched users
  - Session creation after successful Google auth

Architecture:
  Frontend uses Google Identity Services (GSI) SDK to render the
  "Sign in with Google" button. On success, GSI returns a JWT
  credential (ID token) which is POSTed to /auth/google/callback.
  This module verifies that token server-side and creates a session.

Production notes:
  - Only GOOGLE_CLIENT_ID is needed (no client secret for ID token flow)
  - Token verification uses Google's public keys (auto-cached)
  - Works with any domain — just update GOOGLE_CLIENT_ID in .env
  - Authorized JavaScript origins must be set in Google Cloud Console
  - For production: add your domain to Google Cloud Console → Credentials
    → OAuth 2.0 Client IDs → Authorized JavaScript origins

Setup (Google Cloud Console):
  1. Go to https://console.cloud.google.com/apis/credentials
  2. Create Project (or use existing)
  3. Configure OAuth consent screen (External, add your email as test user)
  4. Create Credentials → OAuth 2.0 Client ID → Web application
  5. Add Authorized JavaScript origins:
     - http://localhost:5001 (development)
     - http://127.0.0.1:5001 (development)
     - https://yourdomain.com (production)
  6. Copy Client ID → paste in .env as GOOGLE_CLIENT_ID
"""
from __future__ import annotations

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("auth.google_oauth")


# ═══════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════

def get_google_client_id() -> str:
    """Get Google Client ID from environment."""
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def is_google_auth_enabled() -> bool:
    """Check if Google Sign-In is properly configured."""
    cid = get_google_client_id()
    return bool(cid) and cid != "your-google-client-id.apps.googleusercontent.com"


# ═══════════════════════════════════════════════════════════
#  TOKEN VERIFICATION
# ═══════════════════════════════════════════════════════════

def verify_google_token(id_token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a Google ID token (JWT) and extract user info.

    Uses google-auth library to:
      1. Fetch Google's public keys (cached automatically)
      2. Verify JWT signature, expiry, audience, issuer
      3. Extract user claims (email, name, picture, sub)

    Args:
        id_token: The JWT credential string from Google Identity Services

    Returns:
        Dict with user info on success, None on failure:
        {
            "google_id": "1234567890",
            "email": "user@gmail.com",
            "email_verified": True,
            "first_name": "Rohit",
            "last_name": "Tripathi",
            "full_name": "Rohit Tripathi",
            "picture": "https://lh3.googleusercontent.com/...",
        }
    """
    if not id_token or not id_token.strip():
        logger.warning("Empty Google ID token received")
        return None

    client_id = get_google_client_id()
    if not client_id:
        logger.error("GOOGLE_CLIENT_ID not configured")
        return None

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests

        # Verify the token — this checks signature, expiry, audience, issuer
        idinfo = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            client_id,
        )

        # Verify issuer
        if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            logger.warning("Invalid issuer in Google token: %s", idinfo.get("iss"))
            return None

        # Verify email is present and verified
        email = idinfo.get("email", "").strip().lower()
        if not email:
            logger.warning("No email in Google token")
            return None

        email_verified = idinfo.get("email_verified", False)
        if not email_verified:
            logger.warning("Unverified email in Google token: %s", email)
            return None

        # Extract name parts
        full_name = idinfo.get("name", "").strip()
        given_name = idinfo.get("given_name", "").strip()
        family_name = idinfo.get("family_name", "").strip()

        # Fallback name extraction
        if not given_name and full_name:
            parts = full_name.split(None, 1)
            given_name = parts[0] if parts else ""
            family_name = parts[1] if len(parts) > 1 else ""

        return {
            "google_id": idinfo.get("sub", ""),
            "email": email,
            "email_verified": email_verified,
            "first_name": given_name,
            "last_name": family_name,
            "full_name": full_name or f"{given_name} {family_name}".strip(),
            "picture": idinfo.get("picture", ""),
        }

    except ImportError:
        logger.error(
            "google-auth not installed — run: pip install google-auth"
        )
        return None
    except ValueError as e:
        # Token is invalid (expired, wrong audience, tampered, etc.)
        logger.warning("Google token verification failed: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error verifying Google token: %s", e)
        return None


# ═══════════════════════════════════════════════════════════
#  USER CREATION / LOOKUP
# ═══════════════════════════════════════════════════════════

def google_sign_in(
    id_token: str,
    ip_address: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    """
    Complete Google Sign-In flow:
      1. Verify the ID token
      2. Find existing user by google_id or email
      3. Create new user if first-time sign-in
      4. Create session and return token

    Returns:
        {
            "success": True/False,
            "token": "session-uuid" (on success),
            "user": {...} (on success),
            "error": "message" (on failure),
            "is_new_user": True/False,
        }
    """
    from auth.db import (
        get_user_by_google_id, get_user_by_email,
        create_google_user, link_google_account,
        create_session, update_last_login,
    )

    # Step 1: Verify token
    google_user = verify_google_token(id_token)
    if not google_user:
        return {"success": False, "error": "Invalid or expired Google token. Please try again."}

    google_id = google_user["google_id"]
    email = google_user["email"]
    is_new_user = False

    # Step 2: Find existing user
    # Priority: google_id match > email match > new user
    user = get_user_by_google_id(google_id)

    if not user:
        # Check if email already exists (manual signup user → link accounts)
        user = get_user_by_email(email)
        if user:
            # Link Google account to existing user
            link_google_account(
                user_id=user["id"],
                google_id=google_id,
                profile_picture=google_user.get("picture", ""),
            )
            logger.info("Linked Google account to existing user: %s (id=%d)", email, user["id"])
        else:
            # Step 3: Create new user (first-time Google sign-in)
            user_id = create_google_user(
                google_id=google_id,
                email=email,
                first_name=google_user.get("first_name", ""),
                last_name=google_user.get("last_name", ""),
                profile_picture=google_user.get("picture", ""),
            )
            if user_id is None:
                return {"success": False, "error": "Could not create account. Please try again."}

            user = get_user_by_google_id(google_id)
            if not user:
                return {"success": False, "error": "Account creation failed. Please try again."}

            is_new_user = True
            logger.info("Created new Google user: %s (id=%d)", email, user_id)

    # Check if user is active
    if not user.get("is_active", True):
        return {"success": False, "error": "Account is deactivated. Contact support."}

    # Step 4: Create session
    update_last_login(user["id"])
    token = create_session(user["id"], ip_address, user_agent)

    return {
        "success": True,
        "token": token,
        "is_new_user": is_new_user,
        "user": {
            "id": user["id"],
            "username": user.get("username", ""),
            "email": user.get("email", email),
            "full_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            "profile_picture": user.get("profile_picture", google_user.get("picture", "")),
            "is_admin": bool(user.get("is_admin", False)),
        },
    }
