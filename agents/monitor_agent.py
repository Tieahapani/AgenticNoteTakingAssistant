# backend/agents/monitor_agent.py

import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta, timezone
from collections import Counter
from openai import OpenAI 
from dotenv import load_dotenv
from agents.notification_manager import NotificationManager 

load_dotenv()

class MonitorAgent:
    """
    Production Monitor Agent for VoiceLog AI
    Analyzes user tasks and generates proactive insights
    
    UPDATED: Now works with user-scoped data structure
    """
    
    def __init__(self, firebase_cred_path=None):
        """Initialize Firebase connection"""
        # Initialize Firebase if not already done
        if not firebase_admin._apps:
            if firebase_cred_path is None:
                firebase_cred_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "firebase-credentials.json"
                )
            cred = credentials.Certificate(firebase_cred_path)
            firebase_admin.initialize_app(cred)
        
        self.db = firestore.client()
        self.log("✅ Monitor Agent initialized")
        self.llm_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.notification_manager = None  # Will be set per user in run()
        self.notification_system_prompt = """You are a notification generator for VoiceLog AI, a task management app.

Your job: Convert structured insights into natural, friendly push notifications.

STYLE GUIDELINES:
- Friendly and conversational tone
- Encouraging but not pushy
- Short and scannable (title max 50 chars, body max 120 chars)
- Action-oriented when appropriate
- Include specific details from the data
- Sound like a helpful friend, not a robot

TONE EXAMPLES:
✓ "🔥 3 priority tasks waiting" (not "You have 3 high priority tasks")
✓ "Almost done with daily_tasks!" (not "Folder completion rate: 71%")
✓ "You're crushing it at 7 AM" (not "Peak productivity detected at 7:00")

FORMAT RULES:
- Use emojis sparingly (1 per notification max)
- No markdown, no code blocks, no JSON
- Must provide BOTH title and body
- Each on separate line starting with "Title:" and "Body:"

CRITICAL: Response must be plain text only - no preamble, no explanation, just:
Title: [your title]
Body: [your body]"""

    def log(self, message):
        """Simple logging with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")

    def generate_insight_via_llm(self, insight): 
        """Generate natural notification using LLM"""  
        user_message = f"""Generate notification for this insight: 

Type: {insight['type']}
Priority: {insight['priority']}
Data: {insight['data']}

Provide Title and Body."""

        try:
            response = self.llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self.notification_system_prompt}, 
                    {"role": "user", "content": user_message}
                ]
            )

            if response.choices:
                content = response.choices[0].message.content
                lines = content.strip().split("\n")
                
                # Parse Title and Body
                title = "VoiceLog Insight"
                body = "Check your tasks"
                
                for line in lines:
                    if line.startswith("Title:"):
                        title = line.replace("Title:", "").strip()
                    elif line.startswith("Body:"):
                        body = line.replace("Body:", "").strip()
                
                return {"title": title, "body": body}

        except Exception as e:
            self.log(f"❌ Error generating insight via LLM: {e}")
            return {"title": "VoiceLog Insight", "body": "New insight available"}

    # ========================================
    # DATA FETCHING (UPDATED FOR USER SCOPING)
    # ========================================
    
    def get_all_tasks(self, user_id: str):
        """
        Fetch all tasks for a specific user from Firebase
        
        CHANGED: Now queries user-specific collection
        Path: users/{user_id}/tasks
        """
        try:
            # NEW: User-specific path
            tasks_ref = self.db.collection('users').document(user_id).collection('tasks')
            tasks = tasks_ref.stream()
            
            task_list = []
            for task in tasks:
                task_data = task.to_dict()
                task_data['id'] = task.id
                task_list.append(task_data)
            
            self.log(f"📋 Fetched {len(task_list)} tasks for user {user_id}")
            return task_list
        
        except Exception as e:
            self.log(f"❌ Error fetching tasks for user {user_id}: {e}")
            return []
    
    # ========================================
    # INSIGHT GENERATORS (NO CHANGES NEEDED)
    # ========================================
    
    def check_high_priority_tasks(self, tasks):
        """Alert on high priority tasks that aren't completed"""
        insights = []
        now = datetime.now(timezone.utc)
        
        incomplete_priority = [
            t for t in tasks 
            if t.get('is_high_priority') and not t.get('completed')
        ]
        
        if len(incomplete_priority) >= 3:
            task_names = [t['name'] for t in incomplete_priority[:5]]
            
            insight = {
                "type": "priority_alert",
                "priority": "high",
                "created_at": now.isoformat(),
                "read": False,
                "dismissed": False,
                "data": {
                    "count": len(incomplete_priority),
                    "task_names": task_names
                },
            }
            insights.append(insight)
            self.log(f"⚡ Generated priority alert: {len(incomplete_priority)} tasks")
        
        return insights
    
    def check_folder_activity(self, tasks):
        """Analyze which folder user is most active in"""
        insights = []
        now = datetime.now(timezone.utc)
        
        # Count tasks by folder
        folder_counts = Counter()
        completed_by_folder = Counter()
        
        for task in tasks:
            folder = task.get('folder', 'No Folder')
            folder_counts[folder] += 1
            if task.get('completed'):
                completed_by_folder[folder] += 1
        
        if folder_counts:
            most_active_folder = folder_counts.most_common(1)[0]
            folder_name, task_count = most_active_folder
            completed_count = completed_by_folder.get(folder_name, 0)
            completion_rate = (completed_count / task_count * 100) if task_count > 0 else 0
            
            insight = {
                "type": "folder_focus_insight",
                "priority": "low",
                "created_at": now.isoformat(),
                "read": False,
                "dismissed": False,
                "data": {
                    "folder": folder_name,
                    "total_tasks": task_count,
                    "completed_tasks": completed_count,
                    "completion_rate": completion_rate
                },
            }
            insights.append(insight)
            self.log(f"📁 Generated folder insight: {folder_name}")
        
        return insights
    
    def check_completion_patterns(self, tasks, user_timezone="Asia/Kolkata"):
        """Analyze when user completes tasks (in their local timezone)"""
        insights = []
        now = datetime.now(timezone.utc)
        
        completed_tasks = [t for t in tasks if t.get('completed') and t.get('completed_at')]
        
        if len(completed_tasks) < 3:
            self.log("⏭️  Not enough completed tasks for pattern analysis")
            return insights
        
        # Import timezone helper
        try:
            from zoneinfo import ZoneInfo
            local_tz = ZoneInfo(user_timezone)
        except ImportError:
            import pytz
            local_tz = pytz.timezone(user_timezone)
        
        # Extract hours from completed_at (convert to local timezone)
        hours = []
        for task in completed_tasks:
            try:
                completed_at = task['completed_at']
                completed_at_local = completed_at.astimezone(local_tz)
                hours.append(completed_at_local.hour)
            except Exception as e:
                self.log(f"⚠️  Error parsing timestamp: {e}")
                continue
        
        if hours:
            from collections import Counter
            hour_counts = Counter(hours)
            peak_hour = hour_counts.most_common(1)[0][0]
            
            # Convert to 12-hour format
            hour_12 = peak_hour % 12
            hour_12 = 12 if hour_12 == 0 else hour_12
            am_pm = "AM" if peak_hour < 12 else "PM"
            
            insight = {
                "type": "productivity_tip",
                "priority": "low",
                "created_at": now.isoformat(),
                "read": False,
                "dismissed": False,
                "data": {
                    "peak_hour": peak_hour,
                    "peak_hour_12": f"{hour_12}:00 {am_pm}",
                    "completed_count": len(completed_tasks),
                    "timezone": user_timezone
                },
            }
            insights.append(insight)
            self.log(f"🔥 Generated productivity tip: {hour_12}:00 {am_pm} ({user_timezone})")
        
        return insights
    
    def check_stale_tasks(self, tasks):
        """Detect tasks sitting incomplete for >3 days"""
        insights = []
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(days=3)
        
        stale_tasks_found = []
        
        for task in tasks:
            if task.get('completed'):
                continue
            
            created_at = task.get('created_at')
            if not created_at:
                continue
            
            try:
                # Handle both string and Firestore Timestamp
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                elif hasattr(created_at, 'astimezone'):
                    # Already a datetime object
                    pass
                else:
                    continue
                
                if created_at < stale_threshold:
                    days_old = (now - created_at.replace(tzinfo=timezone.utc)).days
                    stale_tasks_found.append({
                        "task_id": task['id'],
                        "task_name": task['name'],
                        "days_old": days_old
                    })
            
            except Exception as e:
                continue
        
        # Create ONE insight for all stale tasks
        if stale_tasks_found:
            insight = {
                "type": "stale_task_warning",
                "priority": "medium",
                "created_at": now.isoformat(),
                "read": False,
                "dismissed": False,
                "data": {
                    "count": len(stale_tasks_found),
                    "tasks": stale_tasks_found[:3]
                },
            }
            insights.append(insight)
            self.log(f"📌 Generated stale task warning: {len(stale_tasks_found)} tasks")
        
        return insights
    
    # ========================================
    # SAVE TO FIREBASE (UPDATED FOR USER SCOPING)
    # ========================================
    
    def save_insights_to_firebase(self, insights, socketio=None, user_id='default_user'):
        """
        Store insights in Firebase with smart notification filtering
        
        CHANGED: Insights now stored per user
        Path: users/{user_id}/monitor_insights
        """
        if not insights:
            self.log("✅ No new insights to save")
            return
        
        self.log(f"\n--- Smart Notification Filtering ---")
        self.log(f"📊 Generated {len(insights)} total insights")
        
        notifications_sent = 0
        notifications_queued = 0
        
        try:
            # NEW: User-specific insights collection
            insights_ref = self.db.collection('users').document(user_id).collection('monitor_insights')
            
            for insight in insights:
                # Save to Firebase (always save for in-app display)
                doc_ref = insights_ref.document()
                doc_ref.set({
                    **insight,
                    'user_id': user_id  # Still store user_id for reference
                })
                
                # ASK NOTIFICATION MANAGER: Should we push this?
                should_send, reason = self.notification_manager.should_send_now(insight)
                
                if should_send:
                    # Generate notification text with LLM
                    notification = self.generate_insight_via_llm(insight)
                    
                    # Send push notification via WebSocket
                    if socketio:
                        socketio.emit('notification', {
                            'title': notification['title'],
                            'body': notification['body'],
                            'type': insight['type'],
                            'priority': insight['priority'],
                            'timestamp': insight['created_at'],
                            'insight_id': doc_ref.id
                        }, room=user_id)
                        
                        self.log(f"📤 SENT: {notification['title']}")
                    
                    # Record that we sent it
                    self.notification_manager.record_sent(insight)
                    notifications_sent += 1
                
                else:
                    # Queued for in-app display only
                    self.log(f"📥 QUEUED: {insight['type']} - {reason}")
                    notifications_queued += 1
            
            self.log(f"\n💾 Saved {len(insights)} insights to Firebase")
            self.log(f"📤 Sent {notifications_sent} push notifications")
            self.log(f"📥 Queued {notifications_queued} for in-app display")
            
            # Show budget stats
            stats = self.notification_manager.get_stats()
            self.log(f"📊 Budget: {stats['budget_remaining']}/{self.notification_manager.daily_budget} remaining today")

        except Exception as e:
            self.log(f"❌ Error saving insights: {e}")
            import traceback
            traceback.print_exc()
    
    # ========================================
    # MAIN EXECUTION (UPDATED)
    # ========================================
    
    def run(self, user_id: str, user_timezone="Asia/Kolkata", socketio=None):
        """
        Main monitor execution - runs all checks for a specific user
        
        CHANGED: Now requires user_id parameter
        
        Args:
            user_id: Firebase UID of the user to analyze
            user_timezone: User's timezone for time-based insights
            socketio: Optional SocketIO instance for push notifications
        """
        self.log("=" * 60)
        self.log(f"🔍 MONITOR AGENT - Starting analysis")
        self.log(f"   User: {user_id}")
        self.log(f"   Timezone: {user_timezone}")
        self.log("=" * 60)
        
        # Initialize notification manager for this user
        self.notification_manager = NotificationManager(user_id)
        
        # Step 1: Get all tasks for this user
        tasks = self.get_all_tasks(user_id)
        
        if not tasks:
            self.log("⚠️  No tasks found. Exiting.")
            return
        
        # Step 2: Run all checks
        all_insights = []
        
        self.log("\n--- Checking High Priority Tasks ---")
        all_insights.extend(self.check_high_priority_tasks(tasks))
        
        self.log("\n--- Checking Folder Activity ---")
        all_insights.extend(self.check_folder_activity(tasks))
        
        self.log("\n--- Checking Completion Patterns ---")
        all_insights.extend(self.check_completion_patterns(tasks, user_timezone))
        
        self.log("\n--- Checking Stale Tasks ---")
        all_insights.extend(self.check_stale_tasks(tasks))
        
        # Step 3: Save to Firebase with smart filtering
        self.save_insights_to_firebase(all_insights, socketio, user_id)
        
        self.log("\n" + "=" * 60)
        self.log(f"✅ Monitor completed! Generated {len(all_insights)} insights")
        self.log("=" * 60)


# ========================================
# COMMAND LINE EXECUTION
# ========================================

if __name__ == "__main__":
    # For testing - you'll need to provide a real user_id
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python monitor_agent.py <user_id>")
        print("Example: python monitor_agent.py gXLno2jNqIP0hTkV7g6zFQCutf83")
        sys.exit(1)
    
    user_id = sys.argv[1]
    monitor = MonitorAgent()
    monitor.run(user_id=user_id, user_timezone="Asia/Kolkata")