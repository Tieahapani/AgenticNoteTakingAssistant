# backend/agents/cleanup_agent.py

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import firebase_admin
from firebase_admin import credentials, firestore

class CleanupAgent:
    """
    Autonomous task/folder cleanup agent.
    
    SIMPLIFIED RULES:
    1. Check due_date first - if passed and incomplete → delete
    2. High priority tasks → never auto-delete, generate insight instead
    3. Untouched for 10+ days → delete (unless high priority)
    4. Empty folders untouched for 10+ days → delete
    
    UPDATED: Now works with user-scoped data structure
    """
    
    def __init__(self, firebase_cred_path=None):
        """Initialize Firebase connection"""
        if not firebase_admin._apps:
            if firebase_cred_path is None:
                # Try environment variable first, fallback to file
                if os.getenv('FIREBASE_CREDENTIALS_JSON'):
                    import json
                    import tempfile
                    creds_json = json.loads(os.getenv('FIREBASE_CREDENTIALS_JSON'))
                temp_creds = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
                json.dump(creds_json, temp_creds)
                temp_creds.close()
                firebase_cred_path = temp_creds.name
            else:
                firebase_cred_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "firebase-credentials.json"
                )
        cred = credentials.Certificate(firebase_cred_path)
        firebase_admin.initialize_app(cred)
        
        self.db = firestore.client()
        self.log("✅ Cleanup Agent initialized")
    
    def log(self, message):
        """Simple logging with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    # ========================================
    # HELPER METHODS: User-scoped references
    # ========================================
    
    def _get_user_tasks_ref(self, user_id: str):
        """Get reference to user's tasks collection"""
        return self.db.collection('users').document(user_id).collection('tasks')
    
    def _get_user_folders_ref(self, user_id: str):
        """Get reference to user's folders collection"""
        return self.db.collection('users').document(user_id).collection('folders')
    
    def _get_user_insights_ref(self, user_id: str):
        """Get reference to user's insights collection"""
        return self.db.collection('users').document(user_id).collection('monitor_insights')
    
    # ========================================
    # MAIN EXECUTION (UPDATED)
    # ========================================
    
    def run(self, user_id: str, user_timezone="Asia/Kolkata", socketio=None):
        """
        Main cleanup execution for a specific user
        
        CHANGED: Now requires user_id parameter
        
        Args:
            user_id: Firebase UID of the user
            user_timezone: User's timezone for time calculations
            socketio: Optional SocketIO instance for notifications
        """
        self.log("=" * 60)
        self.log(f"🧹 CLEANUP AGENT - Starting")
        self.log(f"   User: {user_id}")
        self.log(f"   Timezone: {user_timezone}")
        self.log("=" * 60)
        
        # Get all tasks for this user
        tasks = self._fetch_tasks(user_id)
        self.log(f"📋 Fetched {len(tasks)} tasks")
        
        # Categorize tasks for cleanup
        tasks_to_delete = []
        high_priority_stale_tasks = []
        
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(days=10)
        
        for task in tasks:
            if task.get('completed'):
                continue  # Skip completed tasks
            
            task_name = task['name']
            is_high_priority = task.get('is_high_priority', False)
            due_date = task.get('due_date')
            created_at = task.get('created_at')
            
            # Convert timestamps
            if hasattr(created_at, 'astimezone'):
                created_at_utc = created_at.replace(tzinfo=timezone.utc)
            else:
                continue  # Can't process without timestamp
            
            # RULE 1: Check due_date first (highest priority check)
            if due_date:
                if hasattr(due_date, 'astimezone'):
                    due_date_utc = due_date.replace(tzinfo=timezone.utc)
                    
                    if due_date_utc < now:
                        # Due date passed!
                        days_overdue = (now - due_date_utc).days
                        
                        if is_high_priority:
                            # High priority + overdue → ask user
                            high_priority_stale_tasks.append({
                                'task': task,
                                'reason': f"Overdue by {days_overdue} days (high priority)"
                            })
                        else:
                            # Regular task, overdue → delete
                            tasks_to_delete.append({
                                'task': task,
                                'reason': f"Overdue by {days_overdue} days"
                            })
                        continue  # Move to next task
            
            # RULE 2: Check if untouched for 10+ days (no due date or due date is future)
            if created_at_utc < stale_threshold:
                days_old = (now - created_at_utc).days
                
                if is_high_priority:
                    # High priority + stale → ask user
                    high_priority_stale_tasks.append({
                        'task': task,
                        'reason': f"Untouched for {days_old} days (high priority)"
                    })
                else:
                    # Regular task + stale → delete
                    tasks_to_delete.append({
                        'task': task,
                        'reason': f"Untouched for {days_old} days"
                    })
        
        # Execute cleanup
        self.log(f"\n--- Cleanup Summary ---")
        self.log(f"🗑️  Auto-deleting: {len(tasks_to_delete)}")
        self.log(f"⚠️  High priority needing attention: {len(high_priority_stale_tasks)}")
        
        # Auto-delete regular stale tasks
        for item in tasks_to_delete:
            self._delete_task(item['task']['id'], user_id)
            self.log(f"   ✓ Deleted: {item['task']['name']} ({item['reason']})")
        
        # Generate insights for high priority stale tasks (don't auto-delete)
        for item in high_priority_stale_tasks:
            self._generate_high_priority_insight(item, socketio, user_id)
            self.log(f"   ⚠️  Generated alert: {item['task']['name']}")
        
        # Cleanup empty folders
        deleted_folders = self._cleanup_empty_folders(user_id)
        
        self.log(f"\n--- Final Stats ---")
        self.log(f"Tasks deleted: {len(tasks_to_delete)}")
        self.log(f"High priority alerts: {len(high_priority_stale_tasks)}")
        self.log(f"Folders deleted: {deleted_folders}")
        
        self.log(f"\n{'='*60}")
        self.log(f"✅ Cleanup completed!")
        self.log(f"{'='*60}\n")
    
    # ========================================
    # DATA OPERATIONS (UPDATED)
    # ========================================
    
    def _fetch_tasks(self, user_id: str):
        """
        Fetch all tasks for specific user
        
        CHANGED: Uses user-scoped collection
        Path: users/{user_id}/tasks
        """
        tasks_ref = self._get_user_tasks_ref(user_id)
        tasks = []
        
        for task in tasks_ref.stream():
            task_data = task.to_dict()
            task_data['id'] = task.id
            tasks.append(task_data)
        
        return tasks
    
    def _delete_task(self, task_id: str, user_id: str):
        """
        Delete a task from Firebase for specific user
        
        CHANGED: Uses user-scoped collection
        """
        try:
            self._get_user_tasks_ref(user_id).document(task_id).delete()
        except Exception as e:
            self.log(f"❌ Error deleting task: {e}")
    
    def _generate_high_priority_insight(self, item, socketio, user_id: str):
        """
        Generate insight for high priority stale task - asks user what to do
        
        CHANGED: Saves to user-scoped insights collection
        Path: users/{user_id}/monitor_insights
        """
        task = item['task']
        reason = item['reason']
        
        insight = {
            "type": "high_priority_stale_warning",
            "priority": "high",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "read": False,
            "dismissed": False,
            "resolved": False, 
            "resolved_at": None, 
            "resolution_action": None, 
            "data": {
                "task_id": task['id'],
                "task_name": task['name'],
                "reason": reason,
                "action_required": True, 
                "folder": task.get('folder', 'unknown')
            }
        }
        
        # Save to user-specific insights collection
        try:
            insights_ref = self._get_user_insights_ref(user_id)
            doc_ref = insights_ref.document()
            doc_ref.set(insight)
            insight_id = doc_ref.id
            
            # Send notification to this user's room
            if socketio:
                socketio.emit('notification', {
                    'title': f"⚠️ High priority task needs attention",
                    'body': f"'{task['name']}' has been {reason}. Complete it or delete it?",
                    'type': 'high_priority_stale_warning',
                    'priority': 'high',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'insight_id': insight_id, 
                    'task_id': task['id'],
                    'task_name': task['name'], 
                    'actions': ['complete', 'delete', 'keep']
                }, room=user_id)
            
            self.log(f"   📤 Sent high priority alert for: {task['name']}")
            
        except Exception as e:
            self.log(f"❌ Error generating insight: {e}")
    
    def _cleanup_empty_folders(self, user_id: str):
        """
        Delete folders that have no tasks and weren't touched in 10+ days
        
        CHANGED: Uses user-scoped collections
        Path: users/{user_id}/folders and users/{user_id}/tasks
        """
        folders = self._get_user_folders_ref(user_id).stream()
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(days=10)
        deleted_count = 0
        
        for folder in folders:
            folder_data = folder.to_dict()
            folder_id = folder.id
            created_at = folder_data.get('created_at')
            
            # Check if folder has any tasks (for this user)
            tasks_in_folder = list(
                self._get_user_tasks_ref(user_id)
                .where('folder', '==', folder_id)
                .limit(1)
                .stream()
            )
            
            if not tasks_in_folder:
                # Empty folder
                if created_at and hasattr(created_at, 'astimezone'):
                    created_at_utc = created_at.replace(tzinfo=timezone.utc)
                    
                    if created_at_utc < stale_threshold:
                        # Delete empty, stale folder
                        try:
                            self._get_user_folders_ref(user_id).document(folder_id).delete()
                            deleted_count += 1
                            self.log(f"   🗑️  Deleted empty folder: {folder_data.get('name', folder_id)}")
                        except Exception as e:
                            self.log(f"❌ Error deleting folder: {e}")
        
        return deleted_count


# ========================================
# COMMAND LINE EXECUTION
# ========================================

if __name__ == "__main__":
    # For testing - you'll need to provide a real user_id
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python cleanup_agents.py <user_id>")
        print("Example: python cleanup_agents.py gXLno2jNqIP0hTkV7g6zFQCutf83")
        sys.exit(1)
    
    user_id = sys.argv[1]
    cleanup = CleanupAgent()
    cleanup.run(user_id=user_id, user_timezone="Asia/Kolkata")