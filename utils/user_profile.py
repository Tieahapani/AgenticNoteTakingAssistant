# backend/utils/user_profile.py

import firebase_admin
from firebase_admin import credentials, firestore
import os

class UserProfile:
    """Manages user profile and settings including timezone"""
    
    def __init__(self):
        if not firebase_admin._apps:
            firebase_cred_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "firebase-credentials.json"
            )
            cred = credentials.Certificate(firebase_cred_path)
            firebase_admin.initialize_app(cred)
        
        self.db = firestore.client()
    
    def _get_profile_ref(self, user_id: str):
        """Get reference to user's profile document"""
        return (self.db.collection('users')
                .document(user_id)
                .collection('profile')
                .document('settings'))
    
    def get_timezone(self, user_id: str) -> str:
        """Get user's timezone, defaults to UTC"""
        try:
            profile_ref = self._get_profile_ref(user_id)
            profile_doc = profile_ref.get()
            
            if profile_doc.exists:
                timezone = profile_doc.to_dict().get('timezone', 'UTC')
                print(f"📍 Timezone for {user_id[:10]}...: {timezone}")
                return timezone
            else:
                print(f"⚠️ No profile, defaulting to UTC")
                return 'UTC'
        except Exception as e:
            print(f"❌ Error getting timezone: {e}")
            return 'UTC'
    
    def set_timezone(self, user_id: str, timezone: str):
        """Set user's timezone"""
        try:
            profile_ref = self._get_profile_ref(user_id)
            profile_doc = profile_ref.get()
            
            if profile_doc.exists:
                profile_ref.update({
                    'timezone': timezone,
                    'updated_at': firestore.SERVER_TIMESTAMP
                })
            else:
                profile_ref.set({
                    'timezone': timezone,
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'updated_at': firestore.SERVER_TIMESTAMP
                })
            
            print(f"✅ Timezone set to {timezone} for {user_id[:10]}...")
        except Exception as e:
            print(f"❌ Error setting timezone: {e}")
    
    def get_profile(self, user_id: str) -> dict:
        """Get full user profile"""
        try:
            profile_ref = self._get_profile_ref(user_id)
            profile_doc = profile_ref.get()
            
            if profile_doc.exists:
                return profile_doc.to_dict()
            return {'timezone': 'UTC'}
        except Exception as e:
            print(f"❌ Error: {e}")
            return {'timezone': 'UTC'}


# Singleton
_user_profile = None

def get_user_profile():
    global _user_profile
    if _user_profile is None:
        _user_profile = UserProfile()
    return _user_profile