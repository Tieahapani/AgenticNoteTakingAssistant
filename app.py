# app.py - Complete with WebSocket and Firebase Authentication

import eventlet 
eventlet.monkey_patch()
import os

# Add the project root to the Python path
# This allows for absolute imports from the 'backend' directory


from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import os
import threading
import json 
import tempfile 

import asyncio
import time
from utils.timing import LatencyTracker
from datetime import datetime
from datetime import timezone 
from auth import verify_token, get_current_user_id
from dotenv import load_dotenv
from utils.firebase_client import FirebaseClient
from utils.user_profile import get_user_profile 
# Try relative import if running as a script, or adjust sys.path if needed

from agents.voicelog_graph import voicelog_app, _postgres_store
from agents.monitor_agent import MonitorAgent
from agents.cleanup_agents import CleanupAgent
from firebase_admin import auth as firebase_auth

load_dotenv()

firebase_cred_path = None

if os.getenv('FIREBASE_CREDENTIALS_JSON'):
    # Running on Render - credentials in environment variable
    print("🔧 Loading Firebase credentials from environment variable...")
    creds_json = json.loads(os.getenv('FIREBASE_CREDENTIALS_JSON'))
    
    # Create temporary file with credentials
    temp_creds = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    json.dump(creds_json, temp_creds)
    temp_creds.close()
    
    firebase_cred_path = temp_creds.name
    print(f"✅ Firebase credentials loaded to: {firebase_cred_path}")
else:
    # Running locally - use file path
    firebase_cred_path = os.path.join(os.path.dirname(__file__), "firebase-credentials.json")
    print(f"🔧 Using local Firebase credentials: {firebase_cred_path}")

app = Flask(__name__)
CORS(app, origins="*")  # Allow Flutter to connect

# Initialize SocketIO
socketio = SocketIO(
    app, 
    cors_allowed_origins="*",  # Allow all origins (restrict in production!)
    async_mode='eventlet',
    logger=True,
    engineio_logger=True
)

print(f"App Startup - Store available: {_postgres_store is not None}")

# ============================================
# INITIALIZE CLIENTS
# ============================================

firebase_client = FirebaseClient()
user_profile = get_user_profile()


# ============================================
# WEBSOCKET EVENTS
# ============================================

@socketio.on('connect')
def handle_connect():
    """Client connects to WebSocket - verify authentication"""
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        print("❌ WebSocket connection rejected: No token")
        emit('error', {'message': 'Connection rejected by server'})
        return False  # Reject connection
    
    try:
        # Verify Firebase token
        if not auth_header.startswith('Bearer '):
            print("❌ WebSocket connection rejected: Invalid auth format")
            emit('error', {'message': 'Connection rejected by server'})
            return False
            
        token = auth_header.split('Bearer ')[1]
        

       
        decoded_token = firebase_auth.verify_id_token(token)
          
        user_id = decoded_token['uid']

        print(f"\n{'='*60}")
        print(f"🔌 NEW AUTHENTICATED CONNECTION")
        print(f"   User ID: {user_id}")
        print(f"   Client SID: {request.sid}")
        print(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}\n")
        
        emit('connection_response', {
            'status': 'connected',
            'user_id': user_id,
            'sid': request.sid,
            'message': 'Connected to VoiceLog Monitor Service',
            'timestamp': datetime.now().isoformat()
        })

        return True 
        
    except Exception as e:
        print(f"❌ WebSocket auth failed: {e}")
        import traceback 
        traceback.print_exc()
        emit('error', {'message': 'Connection rejected by server'})
        return False  # Reject connection


@socketio.on('disconnect')
def handle_disconnect():
    """Client disconnects"""
    print(f"\n{'='*60}")
    print(f"🔌 DISCONNECTION")
    print(f"   Client SID: {request.sid}")
    print(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")


@socketio.on('register_user')
def handle_register(data):
    """User registers to receive insights - verify token"""
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        emit('error', {'message': 'Not authenticated'})
        return
    
    try:
        # Verify token and extract user_id
        token = auth_header.split('Bearer ')[1]
        decoded_token = firebase_auth.verify_id_token(token)
        user_id = decoded_token['uid']
        
        # Join user-specific room
        join_room(user_id)
        
        # Add to monitoring
        monitor_service.add_user(user_id)
        
        print(f"\n{'='*60}")
        print(f"👤 USER REGISTERED")
        print(f"   User ID: {user_id}")
        print(f"   Room: {user_id}")
        print(f"   SID: {request.sid}")
        print(f"{'='*60}\n")
        
        emit('registered', {
            'user_id': user_id,
            'status': 'registered',
            'message': 'You will receive Monitor insights in real-time',
            'room': user_id
        })
        
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        emit('error', {'message': 'Authentication failed'})


@socketio.on('unregister_user')
def handle_unregister(data):
    """User unregisters - verify token"""
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        return
    
    try:
        token = auth_header.split('Bearer ')[1]
        decoded_token = firebase_auth.verify_id_token(token)
        user_id = decoded_token['uid']
        
        leave_room(user_id)
        
        print(f"\n{'='*60}")
        print(f"👤 USER UNREGISTERED")
        print(f"   User ID: {user_id}")
        print(f"{'='*60}\n")
        
        emit('unregistered', {
            'user_id': user_id,
            'status': 'unregistered'
        })
        
    except Exception as e:
        print(f"❌ Unregistration failed: {e}")


@socketio.on('ping')
def handle_ping():
    """Heartbeat check"""
    print(f"💓 Ping from {request.sid}")
    emit('pong', {
        'timestamp': datetime.now().isoformat(),
        'message': 'Server is alive'
    })


# ============================================
# MONITOR SERVICE WITH WEBSOCKET
# ============================================

class MonitorService:
    """Monitor Service with WebSocket push notifications"""
    
    def __init__(self, check_interval=1800):
        self.running = False
        self.check_interval = check_interval
        self.monitored_users = []  # Start with empty list - users added when they authenticate
        self.socketio = None 
        self.last_cleanup_date = None
    
    def set_socketio(self, socketio_instance):
        """Connect SocketIO for pushing notifications"""
        self.socketio = socketio_instance
        print("🔌 SocketIO connected to Monitor Service")
    
    def start(self):
        if self.running:
            print("⚠️  Monitor already running")
            return
        
        self.running = True
        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        thread.start()
        
        print(f"\n{'='*60}")
        print(f"🤖 MONITOR SERVICE STARTED")
        print(f"   Check interval: {self.check_interval}s")
        print(f"   WebSocket: {'✅ Enabled' if self.socketio else '❌ Disabled'}")
        print(f"   Monitored users: {len(self.monitored_users)} users")
        print(f"   Cleanup: Sunday 8-10 PM")
        print(f"{'='*60}\n")
    
    def stop(self):
        self.running = False
        print("\n🛑 Monitor Service stopped")
    
    def add_user(self, user_id):
        if user_id not in self.monitored_users:
            self.monitored_users.append(user_id)
            print(f"👤 Added {user_id} to monitoring list")
    
    def _monitor_loop(self):
        """Main monitoring loop - runs in background thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while self.running:
            try:
                if len(self.monitored_users) == 0:
                    print(f"⏸️  No users to monitor. Waiting {self.check_interval}s...\n")
                    time.sleep(self.check_interval)
                    continue
                
                for user_id in self.monitored_users:
                    loop.run_until_complete(self._check_user(user_id))

                self._check_cleanup_schedule()    
                
                print(f"⏸️  Waiting {self.check_interval}s before next check...\n")
                time.sleep(self.check_interval)
                
            except Exception as e:
                print(f"❌ Monitor loop error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(self.check_interval)
    
    async def _check_user(self, user_id):
        """Check user behavior and push insights via WebSocket"""
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"{'='*60}")
        print(f"[{timestamp}] 🔍 MONITOR CHECKING: {user_id}")
        print(f"{'='*60}")
        
        try:
            # Get Firebase credentials path
            firebase_cred_path = os.path.join(
                os.path.dirname(__file__),
                "firebase-credentials.json"
            )
            
            # Create MonitorAgent and run with socketio + user_id
            user_timezone = user_profile.get_timezone(user_id)
            monitor = MonitorAgent(firebase_cred_path=firebase_cred_path)
        
            monitor.run(
                user_timezone=user_timezone,   # TODO: Get from user profile
                socketio=self.socketio,
                user_id=user_id
            )
            
            print(f"✅ Monitor completed for {user_id}")
            print(f"💾 Insights saved & notifications sent")
        
        except Exception as e:
            print(f"❌ Error checking user {user_id}: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"{'='*60}\n")

    def _check_cleanup_schedule(self): 
        """Check if it's time for weekly cleanup"""
        now = datetime.now()
        today = now.date()

        if now.weekday() == 6 and 20 <= now.hour < 22: 
            if self.last_cleanup_date != today: 
                print(f"\n{'='*60}")
                print(f"🧹 WEEKLY CLEANUP TRIGGERED")
                print(f"   Time: {now.strftime('%A, %B %d at %I:%M %p')}")
                print(f"{'='*60}\n")
                
                self._run_cleanup()
                self.last_cleanup_date = today
    

    def _run_cleanup(self):
        """Run cleanup agent for all monitored users"""
        try:
            firebase_cred_path = os.path.join(
                os.path.dirname(__file__),
                "firebase-credentials.json"
            )
            
            for user_id in self.monitored_users:
                user_timezone = user_profile.get_timezone(user_id)
                cleanup = CleanupAgent(firebase_cred_path=firebase_cred_path)
                cleanup.run(
                    user_timezone=user_timezone,
                    socketio=self.socketio,
                    user_id=user_id
                )
                
                print(f"✅ Cleanup completed for {user_id}\n")
        
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")
            import traceback
            traceback.print_exc()


# Initialize Monitor Service
monitor_service = MonitorService(check_interval=1800)  # 30 minutes


# ============================================
# API ENDPOINTS WITH AUTHENTICATION
# ============================================

# ============================================
# USER PROFILE ENDPOINTS
# ============================================

@app.route('/api/user/timezone', methods=['POST'])
@verify_token
def set_user_timezone():
    """Set user's timezone"""
    user_id = request.user_id
    data = request.get_json()
    timezone = data.get('timezone')
    
    if not timezone:
        return jsonify({'success': False, 'error': 'Timezone required'}), 400
    
    try:
        user_profile.set_timezone(user_id, timezone)
        return jsonify({'success': True, 'timezone': timezone})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/profile', methods=['GET'])
@verify_token
def get_user_profile_endpoint():
    """Get user's profile"""
    user_id = request.user_id
    
    try:
        profile = user_profile.get_profile(user_id)
        return jsonify({'success': True, 'profile': profile})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/create_folder", methods=["POST"])
@verify_token
def api_create_folder():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    folder_name = data["folder_name"].strip().title()
    emoji = data.get("emoji", "").strip()
    result = firebase_client.create_folder(folder_name, emoji, user_id)
    return jsonify({"result": result})


@app.route("/api/create_task", methods=["POST"])
@verify_token
def api_create_task():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    result = firebase_client.create_task(
        data["task_name"],
        data["folder_name"],
        user_id,
        data.get("recurrence", "once"),
        data.get("time", ""),
        data.get("duration", "")
    )
    return jsonify({"result": result})


@app.route("/api/move_task", methods=["POST"])
@verify_token
def api_move_task():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    result = firebase_client.move_task(data["task_name"], data["destination_folder"], user_id)
    return jsonify({"result": result})


@app.route("/api/delete_task", methods=["POST"])
@verify_token
def api_delete_task():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    result = firebase_client.delete_task(data["task_name"], user_id)
    return jsonify({"result": result})


@app.route("/api/delete_folder", methods=["POST"])
@verify_token
def api_delete_folder():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    result = firebase_client.delete_folder(data["folder_name"], user_id)
    return jsonify({"result": result})


@app.route("/api/edit_folder_name", methods=["POST"])
@verify_token
def api_edit_folder_name():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    result = firebase_client.edit_folder_name(
        data["old_name"], 
        data["new_name"], 
        data.get("new_emoji"),
        user_id
    )
    return jsonify({"result": result})


@app.route("/api/edit_task", methods=["POST"])
@verify_token
def api_edit_task():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    result = firebase_client.edit_task(
        data["old_task_name"],
        data.get("new_task_name"),
        data.get("new_folder"),
        data.get("new_recurrence"),
        data.get("new_time"),
        data.get("new_duration"),
        user_id
    )
    return jsonify({"result": result})


@app.route("/api/get_folder_contents", methods=["POST"])
@verify_token
def api_get_folder_contents():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    result = firebase_client.get_folder_contents(data["folder_name"], user_id)
    return jsonify({"result": result})


@app.route("/api/list_all_folders", methods=["GET"])
@verify_token
def api_list_all_folders():
    user_id = request.user_id  # From verified token
    result = firebase_client.list_all_folders(user_id)
    return jsonify({"result": result})


@app.route("/api/mark_task_complete", methods=["POST"])
@verify_token
def api_mark_task_complete():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    task_name = data.get("task_name", "").strip()
    
    if not task_name:
        return jsonify({"result": "Error: Task name is required"}), 400
    
    result = firebase_client.mark_task_complete(task_name, user_id)
    return jsonify({"result": result})


@app.route("/api/mark_task_incomplete", methods=["POST"])
@verify_token
def api_mark_task_incomplete():
    user_id = request.user_id  # From verified token
    data = request.get_json()
    task_name = data.get("task_name", "").strip()
    
    if not task_name:
        return jsonify({"result": "Error: Task name is required"}), 400
    
    result = firebase_client.mark_task_incomplete(task_name, user_id)
    return jsonify({"result": result})


@app.route("/api/toggle_task", methods=["POST"])
@verify_token
def api_toggle_task():
    """Toggle task completion status by task ID"""
    user_id = request.user_id  # From verified token
    data = request.get_json()
    task_id = data.get("task_id", "").strip()
    completed = data.get("completed", False)
    
    if not task_id:
        return jsonify({"result": "Error: Task ID is required"}), 400
    
    result = firebase_client.toggle_task(task_id, completed, user_id)
    return jsonify({"result": result})


# ============================================
# MAIN AGENT ROUTE
# ============================================

@app.route('/process_command', methods=['POST'])
@verify_token  # Verify Firebase token
def process_command():
    """Main entry point - uses LangGraph workflow"""
    data = request.json
    user_command = data.get('command', '')
    user_id = request.user_id  # Get from verified token, not from request body

    if not user_command:
        return jsonify({"error": "No command provided", "success": False}), 400

    # Add user to monitoring
    monitor_service.add_user(user_id)

    thread_id = f"user_{user_id}"

    print(f"\n{'='*60}")
    print(f"📨 User: {user_id}")
    print(f"💬 Command: {user_command}")
    print(f"🧵 Thread: {thread_id}")
    print(f"{'='*60}")

    try:

        tracker = LatencyTracker()
        tracker.start("Total Request")
        config_to_use = {
            "configurable": {
                "thread_id": thread_id, 
                "user_id": user_id
            }
        }

        user_timezone = user_profile.get_timezone(user_id)

        result = voicelog_app.invoke(
            {"user_command": user_command, "user_timezone": user_timezone},
            config_to_use
        )

        tracker.end("Total Request")

        response = result.get("final_response", "Command processed!")
        route = result.get("route_decision", "unknown")

        summary = tracker.get_summary()

        print(f"\n🔀 Route: {route.upper()}")
        print(f"\n📊 TIMING SUMMARY:")
        print(f"   Total: {summary['total_time']}s")
        for op, time_val in summary['operations'].items():
            if op != "Total Request":
                print(f"   - {op}: {time_val}s")
        print(f"✅ Response: {response}")
        print(f"{'='*60}\n")
        
        # LOG TO FILE
        tracker.log_to_file(user_command, response)

        return jsonify({
            "success": True,
            "response": response,
            "latency": summary['total_time'],
            "breakdown": summary['operations']
        })


    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print(f"{'='*60}\n")

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================
# MONITOR ENDPOINTS
# ============================================

@app.route('/api/monitor/status', methods=['GET'])
@verify_token
def monitor_status():
    """Check Monitor Service status"""
    return jsonify({
        "running": monitor_service.running,
        "interval_seconds": monitor_service.check_interval,
        "monitored_users": monitor_service.monitored_users,
        "user_count": len(monitor_service.monitored_users),
        "websocket_enabled": monitor_service.socketio is not None
    })


@app.route('/api/monitor/trigger', methods=['POST'])
@verify_token
def trigger_monitor():
    """Manually trigger Monitor Agent"""
    try:
        user_id = request.user_id  # From verified token
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(monitor_service._check_user(user_id))
        
        return jsonify({
            "success": True,
            "message": f"Monitor triggered for {user_id}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================
# HEALTH CHECK
# ============================================

@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "langgraph_initialized": voicelog_app is not None,
        "firebase_connected": firebase_client.db is not None,
        "firebase_auth_enabled": True,
        "checkpointer": "SQLite (voicelog_memory.db)", 
        "store": "PostgresStore (user preferences)",
        "monitor_service": {
            "running": monitor_service.running,
            "interval": monitor_service.check_interval,
            "users": len(monitor_service.monitored_users),
            "websocket": monitor_service.socketio is not None
        },
        "websocket": {
            "enabled": True,
            "url": "ws://agenticnotetakingassistant-2.onrender.com"
        }
    })


# ============================================
# MOBILE APP ROUTES
# ============================================

@app.route("/folders")
@verify_token
def get_folders():
    """Get all folders for authenticated user"""
    user_id = request.user_id  # From verified token
    
    # Query user-specific folders
    folders = firebase_client.db.collection('users').document(user_id).collection('folders').stream()
    folder_list = []
    
    for folder in folders:
        folder_data = folder.to_dict()
        folder_list.append({
            'id': folder.id,
            'name': folder_data['name'],
            'emoji': folder_data.get('emoji', '')
        })
    
    return jsonify({"folders": folder_list, "success": True})


@app.route("/folders/<fid>/tasks")
@verify_token
def get_tasks(fid):
    """Get tasks in a specific folder for authenticated user"""
    user_id = request.user_id  # From verified token
    
    # Query user-specific tasks
    tasks = firebase_client.db.collection('users').document(user_id).collection('tasks').where('folder', '==', fid).stream()
    task_list = []
    
    for task in tasks:
        task_data = task.to_dict()
        task_list.append({
            'id': task.id,
            'name': task_data['name'],
            'completed': task_data.get('completed', False),
            'recurrence': task_data.get('recurrence', 'once'),
            'time': task_data.get('time'),
            'duration': task_data.get('duration'),
            'folder': task_data['folder']
        })
    
    return jsonify({"tasks": task_list, "success": True})


@app.route("/tasks")
@verify_token
def all_tasks():
    """Get all tasks for authenticated user"""
    user_id = request.user_id  # From verified token
    
    # Query user-specific tasks
    tasks = firebase_client.db.collection('users').document(user_id).collection('tasks').stream()
    task_list = []
    
    for task in tasks:
        task_data = task.to_dict()
        task_list.append({
            'id': task.id,
            'name': task_data['name'],
            'completed': task_data.get('completed', False),
            'folder': task_data['folder']
        })
    
    return jsonify({"tasks": task_list, "success": True})


# ============================================
# START SERVER
# ============================================

if __name__ == "__main__":
    FLASK_PORT = 5002
    
    print(f"\n{'='*60}")
    print(f"🎯 VoiceLog AI Backend Server with WebSocket & Auth")
    print(f"{'='*60}")
    print(f"📡 HTTP Server: http://localhost:{FLASK_PORT}")
    print(f"🔌 WebSocket: ws://localhost:{FLASK_PORT}")
    print(f"🔐 Authentication: Firebase Auth Enabled")
    print(f"\n📋 Main Endpoints:")
    print(f"   POST /process_command - Main chat (Auth Required)")
    print(f"   GET  /api/monitor/status - Monitor status (Auth Required)")
    print(f"   POST /api/monitor/trigger - Manual trigger (Auth Required)")
    print(f"   GET  /health - Health check (No Auth)")
    print(f"\n🔌 WebSocket Events:")
    print(f"   Client → Server: register_user, ping (Auth Required)")
    print(f"   Server → Client: notification, connection_response, pong")
    print(f"\n🤖 Monitor Service: Starting in background...")
    print(f"{'='*60}\n")
    
    # Connect SocketIO to Monitor Service
    monitor_service.set_socketio(socketio)
    
    # Start Monitor Service
    monitor_service.start()
    
    try:
        # Use socketio.run instead of app.run
        socketio.run(
            app,
            host="0.0.0.0",
            port=FLASK_PORT,
            debug=False,
            use_reloader=False,  # Prevent duplicate threads
            allow_unsafe_werkzeug=True  # For development
        )
    finally:
        monitor_service.stop()