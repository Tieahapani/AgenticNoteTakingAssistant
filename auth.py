import firebase_admin
from firebase_admin import credentials, auth
from functools import wraps
from flask import request, jsonify
import os
import json
import tempfile

# ============================================
# INITIALIZE FIREBASE ADMIN (ONCE)
# ============================================

if not firebase_admin._apps:
    if os.getenv("FIREBASE_CREDENTIALS_JSON"):
        print("🔧 Loading Firebase credentials from environment variable...")
        creds_json = json.loads(os.getenv("FIREBASE_CREDENTIALS_JSON"))

        temp_creds = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        )
        json.dump(creds_json, temp_creds)
        temp_creds.close()

        cred = credentials.Certificate(temp_creds.name)
        print("✅ Firebase credentials loaded from environment")
    else:
        cred_path = os.path.join(
            os.path.dirname(__file__),
            "firebase-credentials.json"
        )
        cred = credentials.Certificate(cred_path)
        print(f"🔧 Using local Firebase credentials: {cred_path}")

    firebase_admin.initialize_app(cred)
    print("✅ Firebase Admin initialized for authentication")


# ============================================
# AUTH DECORATOR (HTTP ONLY)
# ============================================

def verify_token(f):
    """
    Decorator to verify Firebase ID token from Authorization header.
    Adds request.user_id for downstream handlers.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return jsonify({
                "success": False,
                "error": "No authorization token provided"
            }), 401

        if not auth_header.startswith("Bearer "):
            return jsonify({
                "success": False,
                "error": "Invalid authorization format. Use: Bearer <token>"
            }), 401

        try:
            token = auth_header.split("Bearer ")[1]
            decoded_token = auth.verify_id_token(token)

            request.user_id = decoded_token["uid"]

            print(f"✅ Authenticated HTTP user: {request.user_id}")

            return f(*args, **kwargs)

        except auth.InvalidIdTokenError:
            return jsonify({
                "success": False,
                "error": "Invalid or expired token"
            }), 401
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return jsonify({
                "success": False,
                "error": "Authentication failed"
            }), 401

    return decorated_function


def get_current_user_id():
    """Helper for routes protected by @verify_token"""
    return getattr(request, "user_id", None)
