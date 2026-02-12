# utils/firebase_client.py
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json
import pytz 
from dateutil import parser as date_parser 
import os
import re 
import time 
from functools import wraps 
import tempfile 


class FirebaseClient:
    def __init__(self):
        self.db = None
        self._initialize()
    
    def _initialize(self):
        """Initialize Firebase"""
        import tempfile

        print(f"\n{'='*80}")
        print(f"🔧 INITIALIZING FIREBASE CLIENT")
        print(f"{'='*80}")

        try:
            if os.getenv('FIREBASE_CREDENTIALS_JSON'):
                # Running on Render - credentials in environment variable
                print(f"   🌐 Running on Render - using environment credentials")
                cred_dict = json.loads(os.getenv('FIREBASE_CREDENTIALS_JSON'))
                print(f"   📊 Project ID from env: {cred_dict.get('project_id')}")

                # Create temporary file
                temp_creds = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
                json.dump(cred_dict, temp_creds)
                temp_creds.close()

                cred = credentials.Certificate(temp_creds.name)
            else:
                # Running locally - use file path
                print(f"   💻 Running locally - using firebase-credentials.json")
                cred_path = "firebase-credentials.json"

                if not os.path.exists(cred_path):
                    error_msg = f"❌ Credentials file not found: {cred_path}"
                    print(error_msg)
                    raise FileNotFoundError(error_msg)

                print(f"   📄 Loading credentials from: {cred_path}")
                cred = credentials.Certificate(cred_path)

                # Read project ID from credentials
                with open(cred_path, 'r') as f:
                    cred_data = json.load(f)
                    print(f"   📊 Project ID: {cred_data.get('project_id')}")

            if not firebase_admin._apps:
                print(f"   🔧 Initializing Firebase Admin SDK...")
                firebase_admin.initialize_app(cred)
                print(f"   ✅ Firebase Admin SDK initialized")
            else:
                print(f"   ℹ️  Firebase Admin SDK already initialized")

            print(f"   🔧 Getting Firestore client...")
            self.db = firestore.client()
            print(f"   ✅ Firestore client obtained: {self.db}")
            print(f"   ✅ Client type: {type(self.db)}")

            if self.db is None:
                error_msg = "❌ CRITICAL: Firestore client is None!"
                print(error_msg)
                raise Exception(error_msg)

            # Verify we can access Firebase
            app = firebase_admin.get_app()
            print(f"   ✅ Firebase app: {app.name}")
            print(f"   ✅ Project ID: {app.project_id}")

            print(f"✅ Firebase initialization SUCCESSFUL")
            print(f"{'='*80}\n")

        except Exception as e:
            print(f"\n❌ FIREBASE INITIALIZATION FAILED!")
            print(f"   Error type: {type(e).__name__}")
            print(f"   Error message: {str(e)}")
            print(f"{'='*80}\n")
            import traceback
            traceback.print_exc()
            raise
    
    # ============================================
    # HELPER METHOD: Get user collection reference
    # ============================================
    
    def _get_user_folders_ref(self, user_id: str):
        """Get reference to user's folders collection"""
        return self.db.collection('users').document(user_id).collection('folders')
    
    def _get_user_tasks_ref(self, user_id: str):
        """Get reference to user's tasks collection"""
        return self.db.collection('users').document(user_id).collection('tasks')
    
    # ============================================
    # FOLDER OPERATIONS (UPDATED WITH USER_ID)
    # ============================================
    
    def create_folder(self, folder_name: str, emoji: str = "", user_id: str = "default_user"):
        """Create a folder in Firebase for specific user"""
        folder_id = folder_name.lower().replace(" ", "_")
        
        # User-specific path: users/{user_id}/folders/{folder_id}
        folder_ref = self._get_user_folders_ref(user_id).document(folder_id)
        
        if folder_ref.get().exists:
            return f"Folder '{folder_name}' already exists"
        
        folder_ref.set({
            'id': folder_id,
            'name': folder_name,
            'emoji': emoji,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        return f"Created folder {emoji} {folder_name}".strip()
    
    def list_all_folders(self, user_id: str):
        """List all folders for a specific user"""
        folders = self._get_user_folders_ref(user_id).stream()
        folder_list = []
        
        for folder in folders:
            folder_data = folder.to_dict()
            # Count tasks in this folder for this user
            task_count = len(list(
                self._get_user_tasks_ref(user_id)
                .where('folder', '==', folder.id)
                .stream()
            ))
            folder_list.append(f"{folder_data.get('emoji', '')} {folder_data['name']} ({task_count} tasks)")
        
        if not folder_list:
            return "You don't have any folders yet"
        
        return "Your folders:\n" + "\n".join(folder_list)
    
    def delete_folder(self, folder_name: str, user_id: str):
        """Delete a folder and all its tasks"""
        folder_id = folder_name.lower().replace(" ", "_")

        folder_ref = self._get_user_folders_ref(user_id).document(folder_id)
        if not folder_ref.get().exists:
            return f"Folder '{folder_name}' doesn't exist"

        # Delete all tasks in folder
        tasks = self._get_user_tasks_ref(user_id).where('folder', '==', folder_id).stream()
        for task in tasks:
            task.reference.delete()

        folder_ref.delete()
        return f"Deleted folder '{folder_name}'"
    
    def edit_folder_name(self, old_name: str, new_name: str, new_emoji: str = None, user_id: str = None):
        """Rename a folder for a specific user"""
        old_id = old_name.lower().replace(" ", "_")
        new_id = new_name.lower().replace(" ", "_")
        
        old_ref = self._get_user_folders_ref(user_id).document(old_id)
        if not old_ref.get().exists:
            return f"Folder '{old_name}' doesn't exist"
        
        if new_id != old_id:
            new_ref = self._get_user_folders_ref(user_id).document(new_id)
            if new_ref.get().exists:
                return f"A folder named '{new_name}' already exists"
        
        old_data = old_ref.get().to_dict()
        
        new_data = {
            'id': new_id,
            'name': new_name,
            'emoji': new_emoji if new_emoji else old_data.get('emoji', ''),
            'created_at': old_data.get('created_at')
        }
        self._get_user_folders_ref(user_id).document(new_id).set(new_data)
        
        # Update all tasks
        tasks = self._get_user_tasks_ref(user_id).where('folder', '==', old_id).stream()
        for task in tasks:
            task.reference.update({'folder': new_id})
        
        old_ref.delete()
        return f"Renamed folder to '{new_name}'"
    
    def get_folder_contents(self, folder_name: str, user_id: str):
        """Get all tasks in a folder - handles various name formats"""
        # Normalize folder name
        normalized = folder_name.lower().strip()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = normalized.replace(' ', '_')

        print(f"🔍 Looking for folder: '{folder_name}' → normalized: '{normalized}' for user: {user_id}")

        # Check if folder exists
        folder_ref = self._get_user_folders_ref(user_id).document(normalized)
        folder = folder_ref.get()

        if folder.exists:
            folder_data = folder.to_dict()
            display_name = folder_data.get('name', folder_name)
            emoji = folder_data.get('emoji', '')
        else:
            display_name = folder_name
            emoji = ''
            print(f"   ⚠️  Folder document not found, but checking for tasks anyway...")

        # Get tasks in this folder
        tasks = self._get_user_tasks_ref(user_id).where('folder', '==', normalized).stream()
        task_list = []

        for task in tasks:
            task_data = task.to_dict()
            status = "✓" if task_data.get('completed', False) else "○"
            task_list.append(f"{status} {task_data['name']}")

        if not task_list:
            if not folder.exists:
                return f"Folder '{folder_name}' doesn't exist"
            return f"{emoji} {display_name} is empty"

        return f"{emoji} {display_name}:\n" + "\n".join(task_list)
   
    # ============================================
    # TASK OPERATIONS (UPDATED WITH USER_ID)
    # ============================================
    
    def create_task(self, task_name: str, folder_name: str, user_id: str, due_date: str = "",  recurrence: str = "",
                     time: str = "", duration: str = "",):
        """
        Create a new task for a specific user.

        Args:
            task_name: Name of the task
            folder_name: Folder to place task in
            user_id: Firebase UID of the user
            recurrence: once, daily, weekly, etc.
            time: Time for the task
            due_date: Due date for the task in YYYY-MM-DD format (e.g "2026-01-15")
            duration: Duration of the task if mentioned or else estimate
        """
        try:
            folder_id = folder_name.lower().replace(" ", "_")

            # EXTENSIVE LOGGING
            print(f"\n{'='*80}")
            print(f"🔧 CREATE_TASK CALLED")
            print(f"{'='*80}")
            print(f"📝 Task name: '{task_name}'")
            print(f"📁 Folder: '{folder_name}' → '{folder_id}'")
            print(f"👤 User ID: '{user_id}'")
            print(f"🔄 Recurrence: '{recurrence}'")
            print(f"⏰ Time: '{time}'")
            print(f"📅 Due date: '{due_date}'")
            print(f"⏱️  Duration: '{duration}'")

            # Check folder exists — fuzzy match to handle typos like "Probelms" vs "Problems"
            from difflib import SequenceMatcher as SM
            folder_ref = self._get_user_folders_ref(user_id).document(folder_id)
            if not folder_ref.get().exists:
                # Try fuzzy matching against existing folders
                all_folders = list(self._get_user_folders_ref(user_id).stream())
                best_folder = None
                best_sim = 0.0
                for f in all_folders:
                    f_id = f.id
                    f_name = f.to_dict().get('name', f_id)
                    sim = max(
                        SM(None, folder_id, f_id).ratio(),
                        SM(None, folder_name.lower(), f_name.lower()).ratio(),
                    )
                    if sim > best_sim:
                        best_sim = sim
                        best_folder = (f_id, f_name)

                if best_folder and best_sim >= 0.75:
                    # Auto-correct to the closest matching folder
                    folder_id = best_folder[0]
                    print(f"📁 Folder fuzzy match: '{folder_name}' → '{best_folder[1]}' ({best_sim:.0%})")
                else:
                    available = [f.to_dict().get('name', f.id) for f in all_folders]
                    return (
                        f"Folder '{folder_name}' doesn't exist. "
                        f"Available folders: {', '.join(available)}. "
                        f"Create the folder first or use an existing one."
                    )

            # Check for duplicate task name (fuzzy — catches spelling variations)
            from difflib import SequenceMatcher
            existing_tasks = list(self._get_user_tasks_ref(user_id).stream())
            for existing in existing_tasks:
                existing_data = existing.to_dict()
                existing_name = existing_data.get('name', '')
                similarity = SequenceMatcher(None, task_name.lower(), existing_name.lower()).ratio()
                if similarity >= 0.80:
                    existing_folder = existing_data.get('folder', 'unknown')
                    return (
                        f"Task '{existing_name}' already exists in folder '{existing_folder}' "
                        f"(similarity: {similarity:.0%}). Use edit_task to modify it."
                    )

            processed_due_date = None
            if due_date and due_date.strip():
                try:
                     dt = date_parser.parse(due_date.strip())
            # Keep only the calendar date in ISO format
                     processed_due_date = dt.date().isoformat()  # "2026-03-03"
                     print(f"✅ Normalized due date: '{processed_due_date}' from '{due_date}'")
                except Exception as e:
                     print(f"⚠️ Could not parse due_date '{due_date}': {e}")
                     processed_due_date = None 
                # Parse to validate format
                  

            # Check Firebase client status
            print(f"\n🔍 Checking Firebase client...")
            print(f"   self.db: {self.db}")
            print(f"   self.db type: {type(self.db)}")

            if self.db is None:
                error_msg = "❌ CRITICAL ERROR: self.db is None! Firebase not initialized!"
                print(error_msg)
                raise Exception(error_msg)

            print(f"   ✅ Firebase client is initialized")

            # Get tasks collection reference
            print(f"\n🔍 Getting tasks collection reference...")
            tasks_ref = self._get_user_tasks_ref(user_id)
            print(f"   tasks_ref: {tasks_ref}")
            print(f"   tasks_ref type: {type(tasks_ref)}")
            print(f"   tasks_ref path: users/{user_id}/tasks")

            # Create document reference
            print(f"\n🔍 Creating task document reference...")
            task_ref = tasks_ref.document()
            print(f"   task_ref: {task_ref}")
            print(f"   task_ref.id: {task_ref.id}")
            print(f"   task_ref.path: {task_ref.path}")

            # Prepare task data
            print(f"\n🔍 Preparing task data...")
            task_data = {
                'name': task_name,
                'folder': folder_id,
                'completed': False,
                'recurrence': recurrence,
                'time': time,
                'due_date': processed_due_date,
                'duration': duration,

                # Store UTC timestamp
                'created_at': firestore.SERVER_TIMESTAMP,

                # Priority detection
                'is_high_priority': self._detect_priority(task_name),

                # Completion tracking (initially null)
                'completed_at': None,
            }

            print(f"   Task data prepared:")
            for key, value in task_data.items():
                print(f"      {key}: {value}")

            # CRITICAL: Write to Firestore
            print(f"\n🔧 WRITING TO FIRESTORE...")
            print(f"   Path: {task_ref.path}")

            write_result = task_ref.set(task_data)

            print(f"   ✅✅✅ WRITE SUCCESSFUL!")
            print(f"   Write result: {write_result}")
            print(f"   Update time: {write_result.update_time if hasattr(write_result, 'update_time') else 'N/A'}")

            # Verify write (optional but useful for debugging)
            print(f"\n🔍 Verifying task was written...")
            verification = task_ref.get()

            if verification.exists:
                print(f"   ✅ VERIFICATION SUCCESSFUL - Task exists in Firestore!")
                verified_data = verification.to_dict()
                print(f"   Verified task name: {verified_data.get('name')}")
            else:
                print(f"   ⚠️  WARNING: Task does not exist after write (might be eventual consistency)")

            priority_msg = " (High Priority)" if task_data['is_high_priority'] else ""

            success_msg = f"Created task '{task_name}'{priority_msg} in {folder_name}"
            print(f"\n✅ {success_msg}")
            print(f"{'='*80}\n")

            return success_msg

        except Exception as e:
            error_msg = f"❌ EXCEPTION in create_task: {type(e).__name__}: {str(e)}"
            print(f"\n{'='*80}")
            print(error_msg)
            print(f"{'='*80}\n")

            import traceback
            traceback.print_exc()

            raise  # Re-raise to propagate error

    def _detect_priority(self, task_name: str):
        """Detect if task is high priority from name"""
        priority_keywords = [
            'urgent', 'important', 'high priority', 'asap', 
            'critical', 'deadline', 'must', 'emergency'
        ]
        task_lower = task_name.lower()
        return any(keyword in task_lower for keyword in priority_keywords)
    
    def mark_task_complete(self, task_name: str, user_id: str):
        """Mark task complete for specific user"""
        tasks = self._get_user_tasks_ref(user_id).stream()

        for task in tasks:
            task_data = task.to_dict()
            if task_data['name'].lower() == task_name.lower():
                task_ref = self._get_user_tasks_ref(user_id).document(task.id)

                now_utc = datetime.now(pytz.UTC)
                task_ref.update({
                    'completed': True,
                    'completed_at': firestore.SERVER_TIMESTAMP,
                    'completed_day': now_utc.strftime("%A"),
                })

                return f"Marked '{task_name}' as complete ✅"

        return f"Task '{task_name}' not found."
    
    def mark_task_incomplete(self, task_name: str, user_id: str):
        """Mark a task as incomplete for specific user"""
        tasks_ref = self._get_user_tasks_ref(user_id)
        task_query = tasks_ref.where('name', '==', task_name).limit(1)
        task_docs = list(task_query.stream())
        
        if task_docs:
            task_doc = task_docs[0]
            task_doc.reference.update({
                'completed': False,
                'completed_at': None
            })
            return f"Marked '{task_name}' as incomplete"
        
        # Case-insensitive search
        all_tasks = tasks_ref.stream()
        for task in all_tasks:
            task_data = task.to_dict()
            if task_data['name'].lower() == task_name.lower():
                task.reference.update({
                    'completed': False,
                    'completed_at': None
                })
                return f"Marked '{task_data['name']}' as incomplete"
        
        return f"Task '{task_name}' not found"
    
    def toggle_task(self, task_id: str, completed: bool, user_id: str):
        """Toggle task completion by ID for specific user"""
        try:
            task_ref = self._get_user_tasks_ref(user_id).document(task_id)
            task_doc = task_ref.get()
            
            if not task_doc.exists:
                return "Task not found"
            
            if completed:
                now_utc = datetime.now(pytz.UTC)
                task_ref.update({
                    'completed': True,
                    'completed_at': firestore.SERVER_TIMESTAMP,
                    'completed_day': now_utc.strftime("%A"),
                })
                return "success"
            else:
                task_ref.update({
                    'completed': False,
                    'completed_at': None
                })
                return "success"
        except Exception as e:
            return f"Error: {str(e)}"
    
    def delete_task(self, task_name: str, user_id: str):
        """Delete a task for specific user"""
        tasks = self._get_user_tasks_ref(user_id).where('name', '==', task_name).stream()
        
        deleted = False
        for task in tasks:
            task.reference.delete()
            deleted = True
            break
        
        if deleted:
            return f"Deleted task '{task_name}'"
        return f"Task '{task_name}' not found"
    
    def move_task(self, task_name: str, destination_folder: str, user_id: str):
        """Move a task to another folder for specific user"""
        dest_id = destination_folder.lower().replace(" ", "_")
        
        if not self._get_user_folders_ref(user_id).document(dest_id).get().exists:
            return f"Folder '{destination_folder}' doesn't exist"
        
        tasks = self._get_user_tasks_ref(user_id).where('name', '==', task_name).stream()
        
        moved = False
        for task in tasks:
            task.reference.update({'folder': dest_id})
            moved = True
            break
        
        if moved:
            return f"Moved '{task_name}' to {destination_folder}"
        return f"Task '{task_name}' not found"
    
    def edit_task(self, old_task_name: str, new_task_name: str = None, new_folder: str = None,
                  new_recurrence: str = None, new_time: str = None, new_duration: str = None, new_due_date: str = None,  user_id: str = None):
        """Edit task properties for specific user"""
        tasks = self._get_user_tasks_ref(user_id).stream()
        
        for task in tasks:
            task_data = task.to_dict()
            if task_data['name'].lower() == old_task_name.lower():
                updates = {}
                
                if new_task_name:
                    updates['name'] = new_task_name
                    updates['is_high_priority'] = self._detect_priority(new_task_name)
                
                if new_folder:
                    new_id = new_folder.lower().replace(" ", "_")
                    if not self._get_user_folders_ref(user_id).document(new_id).get().exists:
                        return f"Folder '{new_folder}' doesn't exist"
                    updates['folder'] = new_id
                
                if new_recurrence is not None:
                    updates['recurrence'] = new_recurrence
                if new_time is not None:
                    updates['time'] = new_time
                if new_duration is not None:
                    updates['duration'] = new_duration
                if new_due_date is not None: 
                    updates['due_date'] = new_due_date     
                
                if updates:
                    task.reference.update(updates)
                    final_name = new_task_name if new_task_name else old_task_name
                    return f"Updated '{final_name}'"
                else:
                    return "Nothing to update"
        
        return f"Task '{old_task_name}' not found"
    
    # ============================================
    # QUERY OPERATIONS (UPDATED WITH USER_ID)
    # ============================================
    
    def get_all_tasks(self, user_id: str):
        """Get all tasks for specific user (for comprehensive analysis)"""
        tasks = self._get_user_tasks_ref(user_id).stream()
        task_list = []
        
        for task in tasks:
            task_data = task.to_dict()
            task_list.append(self._format_task_data(task.id, task_data))
        
        return task_list
    
    def get_task_by_name(self, task_name: str, user_id: str):
        """Get a specific task by name for specific user"""
        if not task_name or not task_name.strip():
            return None

        task_name = task_name.strip()

        # Try exact match first
        tasks_ref = self._get_user_tasks_ref(user_id)
        task_query = tasks_ref.where('name', '==', task_name).limit(1)
        task_docs = list(task_query.stream())

        if task_docs:
            task_doc = task_docs[0]
            return self._format_task_data(task_doc.id, task_doc.to_dict())

        # Case-insensitive search
        all_tasks = tasks_ref.stream()
        for task in all_tasks:
            task_data = task.to_dict()
            if task_data['name'].lower() == task_name.lower():
                return self._format_task_data(task.id, task_data)

        return None
    
    # ============================================
    # INTERNAL HELPERS
    # ============================================
    
    def _format_task_data(self, task_id: str, task_data: dict):
        """
        Format task data with proper timestamp conversion.
        Converts Firestore Timestamps to ISO strings (UTC).
        """
        return {
            'id': task_id,
            'name': task_data.get('name'),
            'folder': task_data.get('folder'),
            'completed': task_data.get('completed', False),
            'recurrence': task_data.get('recurrence'),
            'time': task_data.get('time'),
            'duration': task_data.get('duration'),
            'is_high_priority': task_data.get('is_high_priority', False),
            'created_at': self._timestamp_to_iso(task_data.get('created_at')),
            'completed_at': self._timestamp_to_iso(task_data.get('completed_at')),
            'due_date': self._timestamp_to_iso(task_data.get('due_date')),
        }
    
    def _timestamp_to_iso(self, timestamp):
        """Convert Firestore timestamp to ISO UTC string"""
        if timestamp is None:
            return None
        
        try:
            # Firestore Timestamp object
            if hasattr(timestamp, 'timestamp'):
                dt = datetime.fromtimestamp(timestamp.timestamp(), tz=pytz.UTC)
                return dt.isoformat()
            
            # Already a datetime
            elif isinstance(timestamp, datetime):
                if timestamp.tzinfo is None:
                    dt = pytz.UTC.localize(timestamp)
                else:
                    dt = timestamp.astimezone(pytz.UTC)
                return dt.isoformat()
            
            # ISO string (pass through)
            elif isinstance(timestamp, str):

                if timestamp.strip(): 
                    try: 
                        datetime.strptime(timestamp.strip(), "%Y-%m-%d")
                        return timestamp.strip()
                    except ValueError: 
                       return timestamp

                return None     
            
            return None
        
        except Exception as e:
            print(f"⚠️ Timestamp conversion error: {e}")
            return None


def firebase_retry(max_attempts=3, delay=1):
    """Decorator to retry Firebase operations on connection errors"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    
                    # Only retry on connection/timeout errors
                    if any(x in error_str for x in ['timeout', 'unavailable', 'deadline', 'connection']):
                        if attempt < max_attempts - 1:
                            print(f"⚠️  Firebase retry {attempt + 1}/{max_attempts}: {e}")
                            time.sleep(delay)
                            continue
                    
                    # Don't retry other errors (like permission denied)
                    raise
            
            raise last_error
        return wrapper
    return decorator