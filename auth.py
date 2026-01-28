import firebase_admin
from firebase_admin import credentials, auth
from functools import wraps
from flask import request, jsonify
import os
import json 
import tempfile 

# Initialize Firebase Admin (only once)
# Check if already initialized to avoid duplicate initialization
if not firebase_admin._apps:
    if os.getenv('FIREBASE_CREDENTIALS_JSON'):
        # Running on Render - credentials in environment variable
        print("🔧 Loading Firebase credentials from environment variable...")
        creds_json = json.loads(os.getenv('FIREBASE_CREDENTIALS_JSON'))
        
        # Create temporary file with credentials
        temp_creds = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        json.dump(creds_json, temp_creds)
        temp_creds.close()
        
        cred = credentials.Certificate(temp_creds.name)
        print(f"✅ Firebase credentials loaded from environment")
    else:
        # Running locally - use file path
        cred_path = os.path.join(os.path.dirname(__file__), "firebase-credentials.json")
        cred = credentials.Certificate(cred_path)
        print(f"🔧 Using local Firebase credentials: {cred_path}")
    
    firebase_admin.initialize_app(cred)
    print("✅ Firebase Admin initialized for authentication")

def verify_token(f):
    """
    Decorator to verify Firebase ID token from Authorization header.
    Extracts user_id and adds it to the request object.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get Authorization header
        auth_header = request.headers.get('Authorization')

        if not auth_header:
            return jsonify({
                'success': False,
                'error': 'No authorization token provided'
            }), 401

        try:
            # Extract token (format: "Bearer <token>")
            if not auth_header.startswith('Bearer '):
                return jsonify({
                    'success': False,
                    'error': 'Invalid authorization format. Use: Bearer <token>'
                }), 401

            token = auth_header.split('Bearer ')[1]

            # Verify token with Firebase using thread pool for gevent compatibility
            try:
                import gevent
                from gevent.threadpool import ThreadPool
                pool = ThreadPool(maxsize=10)
                decoded_token = pool.spawn(auth.verify_id_token, token).get()
            except ImportError:
                # Fallback if gevent not available (local development)
                decoded_token = auth.verify_id_token(token)

            # Extract user ID from verified token
            user_id = decoded_token['uid']

            # Add user_id to request for route handlers to use
            request.user_id = user_id

            print(f"✅ Authenticated user: {user_id}")

            return f(*args, **kwargs)

        except auth.InvalidIdTokenError:
            return jsonify({
                'success': False,
                'error': 'Invalid or expired token'
            }), 401
        except Exception as e:
            print(f"❌ Authentication error: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Authentication failed: {str(e)}'
            }), 401

    return decorated_function


def get_current_user_id():
    """
    Helper function to get current authenticated user ID from request.
    Use this in routes that have @verify_token decorator.
    """
    return getattr(request, 'user_id', None)