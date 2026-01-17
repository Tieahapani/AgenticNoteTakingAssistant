# backend/agents/notification_manager.py

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import firebase_admin
from firebase_admin import credentials, firestore
import os

class NotificationManager:
    """
    Manages when and how to send notifications intelligently.
    
    UPDATED: Now stores state in Firestore instead of local files
    Path: users/{user_id}/notification_state/current
    
    Think of this as a smart filter between your Monitor Agent and the user.
    It decides: "Should I send this now, later, or not at all?"
    """
    
    def __init__(self, user_id: str ):
        """
        Initialize NotificationManager for a specific user
        
        Args:
            user_id: Firebase UID of the user
        """
        self.user_id = user_id
        
        # Initialize Firebase if not already done
        if not firebase_admin._apps:
            import json
            import tempfile
            
            if os.getenv('FIREBASE_CREDENTIALS_JSON'):
                # Running on Render - credentials in environment variable
                creds_json = json.loads(os.getenv('FIREBASE_CREDENTIALS_JSON'))
                temp_creds = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
                json.dump(creds_json, temp_creds)
                temp_creds.close()
                firebase_cred_path = temp_creds.name
            else:
                # Running locally - use file path
                firebase_cred_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "firebase-credentials.json"
                )
            
            cred = credentials.Certificate(firebase_cred_path)
            firebase_admin.initialize_app(cred)
        
        self.db = firestore.client()
        
        # Notification budget - prevents spam
        self.daily_budget = 6  # Max 6 push notifications per day
        self.min_gap_minutes = 120  # 2 hours between non-urgent notifications
        
        # Quiet hours (no notifications during sleep)
        self.quiet_hours_start = 22  # 10 PM
        self.quiet_hours_end = 7     # 7 AM
        
        # Load or initialize state
        self.state = self._load_state()
    
    def _get_state_ref(self):
        """
        Get reference to user's notification state document
        
        Path: users/{user_id}/notification_state/current
        """
        return (self.db.collection('users')
                .document(self.user_id)
                .collection('notification_state')
                .document('current'))
    
    def _load_state(self) -> Dict:
        """
        Load notification state from Firestore
        
        CHANGED: Now reads from Firestore instead of local JSON file
        
        Returns:
            Dictionary containing notification state
        """
        try:
            state_ref = self._get_state_ref()
            state_doc = state_ref.get()
            
            if state_doc.exists:
                state_data = state_doc.to_dict()
                
                # Convert Firestore timestamps to ISO strings for consistency
                if state_data.get('last_notification_time'):
                    timestamp = state_data['last_notification_time']
                    if hasattr(timestamp, 'isoformat'):
                        state_data['last_notification_time'] = timestamp.isoformat()
                
                print(f"✅ Loaded notification state for user {self.user_id}")
                return state_data
            else:
                # Initialize new state
                print(f"🆕 Initializing notification state for user {self.user_id}")
                initial_state = {
                    "sent_today": 0,
                    "last_reset": datetime.now().date().isoformat(),
                    "last_notification_time": None,
                    "notification_history": []
                }
                state_ref.set(initial_state)
                return initial_state
                
        except Exception as e:
            print(f"⚠️ Error loading notification state for {self.user_id}: {e}")
            # Return default state if error
            return {
                "sent_today": 0,
                "last_reset": datetime.now().date().isoformat(),
                "last_notification_time": None,
                "notification_history": []
            }
    
    def _save_state(self):
        """
        Save notification state to Firestore
        
        CHANGED: Now writes to Firestore instead of local JSON file
        """
        try:
            state_ref = self._get_state_ref()
            state_ref.set(self.state)
        except Exception as e:
            print(f"❌ Error saving notification state for {self.user_id}: {e}")
    
    def _reset_daily_counter(self):
        """
        Reset counter at start of new day
        
        Checks if it's a new day and resets the sent_today counter
        """
        today = datetime.now().date().isoformat()
        if self.state["last_reset"] != today:
            self.state["sent_today"] = 0
            self.state["last_reset"] = today
            self._save_state()
            print(f"🔄 Daily notification counter reset for {self.user_id}")
    
    def should_send_now(self, notification: Dict) -> Tuple[bool, str]:
        """
        Main decision function: Should this notification be sent right now?
        
        Args:
            notification: Dictionary containing notification data with 'type' and 'priority'
        
        Returns:
            Tuple of (should_send: bool, reason: str)
        
        Rules:
        1. Critical priority always goes through
        2. Respect quiet hours (10 PM - 7 AM) unless high/critical
        3. Check daily budget (6 notifications/day)
        4. Enforce minimum gap (2 hours between low-priority)
        5. Prevent duplicates (same type within 24 hours)
        """
        self._reset_daily_counter()
        
        priority = notification.get('priority', 'low')
        notif_type = notification.get('type', '')
        
        # Rule 1: CRITICAL always goes through (deadlines, overdue)
        if priority == 'critical':
            return True, "Critical priority - sending immediately"
        
        # Rule 2: Check if we're in quiet hours
        current_hour = datetime.now().hour
        if self.quiet_hours_start <= current_hour or current_hour < self.quiet_hours_end:
            if priority != 'high':
                return False, f"Quiet hours ({self.quiet_hours_start}:00-{self.quiet_hours_end}:00)"
        
        # Rule 3: Check daily budget
        if self.state["sent_today"] >= self.daily_budget:
            if priority != 'high':
                return False, f"Daily budget exhausted ({self.state['sent_today']}/{self.daily_budget})"
        
        # Rule 4: Check minimum gap between notifications
        if self.state["last_notification_time"]:
            try:
                # Handle both string and datetime
                last_time_str = self.state["last_notification_time"]
                if isinstance(last_time_str, str):
                    last_time = datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
                else:
                    last_time = last_time_str
                
                gap = datetime.now() - last_time.replace(tzinfo=None)
                min_gap = timedelta(minutes=self.min_gap_minutes)
                
                if gap < min_gap and priority not in ['high', 'critical']:
                    minutes_left = int((min_gap - gap).total_seconds() / 60)
                    return False, f"Too soon (wait {minutes_left} more minutes)"
            except Exception as e:
                print(f"⚠️ Error checking notification gap: {e}")
        
        # Rule 5: Check for duplicate notifications (same type within 24 hours)
        if self._is_duplicate(notification):
            return False, "Similar notification sent recently"
        
        # All checks passed!
        return True, "All checks passed"
    
    def _is_duplicate(self, notification: Dict) -> bool:
        """
        Check if we sent a similar notification recently (within 24 hours)
        
        Args:
            notification: Dictionary containing notification data
        
        Returns:
            True if duplicate found, False otherwise
        """
        notif_type = notification.get('type', '')
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        for sent in self.state.get("notification_history", []):
            try:
                sent_timestamp = sent.get("timestamp", "")
                if isinstance(sent_timestamp, str):
                    sent_time = datetime.fromisoformat(sent_timestamp.replace('Z', '+00:00'))
                else:
                    sent_time = sent_timestamp
                
                sent_time = sent_time.replace(tzinfo=None)
                
                if sent_time > cutoff_time and sent.get("type") == notif_type:
                    return True
            except Exception as e:
                continue
        
        return False
    
    def record_sent(self, notification: Dict):
        """
        Record that we sent this notification
        
        Updates:
        - Increment daily counter
        - Update last notification time
        - Add to history (keeps last 50)
        - Save to Firestore
        
        Args:
            notification: Dictionary containing notification data
        """
        self.state["sent_today"] += 1
        self.state["last_notification_time"] = datetime.now().isoformat()
        
        # Add to history
        history_entry = {
            "type": notification.get('type'),
            "priority": notification.get('priority'),
            "timestamp": datetime.now().isoformat()
        }
        
        if "notification_history" not in self.state:
            self.state["notification_history"] = []
        
        self.state["notification_history"].append(history_entry)
        
        # Keep only last 50 notifications in history
        self.state["notification_history"] = self.state["notification_history"][-50:]
        
        self._save_state()
        print(f"📊 Notification sent ({self.state['sent_today']}/{self.daily_budget} today) for user {self.user_id}")
    
    def get_stats(self) -> Dict:
        """
        Get notification statistics for this user
        
        Returns:
            Dictionary with current notification stats
        """
        return {
            "user_id": self.user_id,
            "sent_today": self.state.get("sent_today", 0),
            "budget_remaining": self.daily_budget - self.state.get("sent_today", 0),
            "last_notification": self.state.get("last_notification_time"),
            "total_in_history": len(self.state.get("notification_history", [])),
            "last_reset": self.state.get("last_reset"),
            "daily_budget": self.daily_budget,
            "min_gap_minutes": self.min_gap_minutes,
            "quiet_hours": f"{self.quiet_hours_start}:00 - {self.quiet_hours_end}:00"
        }
    
    def reset_for_testing(self):
        """
        Reset all notification state (useful for testing)
        
        WARNING: This clears all notification history!
        """
        initial_state = {
            "sent_today": 0,
            "last_reset": datetime.now().date().isoformat(),
            "last_notification_time": None,
            "notification_history": []
        }
        
        try:
            state_ref = self._get_state_ref()
            state_ref.set(initial_state)
            self.state = initial_state
            print(f"🔄 Notification state reset for user {self.user_id}")
        except Exception as e:
            print(f"❌ Error resetting notification state: {e}")


# ========================================
# COMMAND LINE TESTING
# ========================================

if __name__ == "__main__":
    """
    Test the notification manager
    Usage: python notification_manager.py <user_id>
    """
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python notification_manager.py <user_id>")
        print("Example: python notification_manager.py gXLno2jNqIP0hTkV7g6zFQCutf83")
        sys.exit(1)
    
    user_id = sys.argv[1]
    
    print(f"\n{'='*60}")
    print(f"🧪 NOTIFICATION MANAGER TEST")
    print(f"   User: {user_id}")
    print(f"{'='*60}\n")
    
    manager = NotificationManager(user_id)
    
    # Show current stats
    print("📊 Current Notification Stats:")
    stats = manager.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    # Test a notification
    print("\n🧪 Testing notification decision...")
    test_notification = {
        "type": "test_notification",
        "priority": "low",
        "data": {"message": "This is a test"}
    }
    
    should_send, reason = manager.should_send_now(test_notification)
    print(f"   Should send: {should_send}")
    print(f"   Reason: {reason}")
    
    if should_send:
        print("\n📤 Recording test notification as sent...")
        manager.record_sent(test_notification)
        
        # Show updated stats
        print("\n📊 Updated Stats:")
        stats = manager.get_stats()
        for key, value in stats.items():
            print(f"   {key}: {value}")
    
    print(f"\n{'='*60}")
    print("✅ Test completed!")
    print(f"{'='*60}\n")