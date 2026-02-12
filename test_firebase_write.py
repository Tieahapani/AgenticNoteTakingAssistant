#!/usr/bin/env python3
"""
Test script to debug Firebase task writing issues.
This bypasses LangGraph and directly tests Firebase writes.
"""

import sys
import os
import traceback
from datetime import datetime
import time

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 80)
print("FIREBASE TASK WRITE DEBUG TEST")
print("=" * 80)
print()

# Test 1: Import firebase_admin
print("1️⃣  Testing firebase_admin import...")
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    print("   ✅ firebase_admin imported successfully")
    print(f"   📦 firebase_admin version: {firebase_admin.__version__}")
except Exception as e:
    print(f"   ❌ FAILED to import firebase_admin: {e}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 2: Initialize Firebase
print("2️⃣  Testing Firebase initialization...")
try:
    if firebase_admin._apps:
        print("   ⚠️  Firebase already initialized, using existing app")
        db = firestore.client()
    else:
        cred_path = "firebase-credentials.json"
        if not os.path.exists(cred_path):
            print(f"   ❌ Credentials file not found: {cred_path}")
            sys.exit(1)

        print(f"   📄 Loading credentials from: {cred_path}")
        cred = credentials.Certificate(cred_path)

        print("   🔧 Initializing Firebase Admin SDK...")
        firebase_admin.initialize_app(cred)

        print("   🔧 Getting Firestore client...")
        db = firestore.client()

    print(f"   ✅ Firebase initialized successfully")
    print(f"   📊 Firestore client: {db}")
    print(f"   📊 Client type: {type(db)}")
except Exception as e:
    print(f"   ❌ FAILED to initialize Firebase: {e}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 3: Verify project configuration
print("3️⃣  Testing project configuration...")
try:
    app = firebase_admin.get_app()
    print(f"   ✅ Firebase app name: {app.name}")
    print(f"   ✅ Project ID: {app.project_id}")

    expected_project = "voicelog-ai-dc521"
    if app.project_id != expected_project:
        print(f"   ⚠️  WARNING: Project ID mismatch!")
        print(f"      Expected: {expected_project}")
        print(f"      Got: {app.project_id}")
except Exception as e:
    print(f"   ⚠️  Could not verify project config: {e}")
print()

# Test 4: Test user document path
USER_ID = "gXLno2jNqIP0hTkV7g6zFQCutf83"
print(f"4️⃣  Testing user document access...")
print(f"   👤 User ID: {USER_ID}")
try:
    user_ref = db.collection('users').document(USER_ID)
    user_doc = user_ref.get()

    if user_doc.exists:
        print(f"   ✅ User document EXISTS")
        print(f"   📊 User data: {user_doc.to_dict()}")
    else:
        print(f"   ⚠️  User document DOES NOT EXIST")
        print(f"   🔧 Creating user document...")
        user_ref.set({
            'created_at': firestore.SERVER_TIMESTAMP,
            'test_created': True
        })
        print(f"   ✅ User document created")
except Exception as e:
    print(f"   ❌ FAILED to access user document: {e}")
    traceback.print_exc()
print()

# Test 5: Check existing tasks
print(f"5️⃣  Checking existing tasks...")
try:
    tasks_ref = db.collection('users').document(USER_ID).collection('tasks')
    print(f"   📍 Tasks collection path: users/{USER_ID}/tasks")

    existing_tasks = list(tasks_ref.stream())
    print(f"   📊 Found {len(existing_tasks)} existing tasks")

    if existing_tasks:
        print("   📋 Existing tasks:")
        for task in existing_tasks:
            task_data = task.to_dict()
            print(f"      - {task.id}: {task_data.get('name', 'NO NAME')}")
    else:
        print("   ℹ️  No existing tasks found")
except Exception as e:
    print(f"   ❌ FAILED to read tasks: {e}")
    traceback.print_exc()
print()

# Test 6: Write a new task
print(f"6️⃣  Writing a new test task...")
test_task_data = {
    'name': 'TEST TASK - Debug Write ' + datetime.now().strftime("%H:%M:%S"),
    'folder': 'daily_tasks',
    'completed': False,
    'recurrence': 'once',
    'time': '',
    'due_date': '',
    'duration': '',
    'created_at': firestore.SERVER_TIMESTAMP,
    'is_high_priority': False,
    'completed_at': None,
    'test_task': True  # Flag to identify test tasks
}

print(f"   📝 Task data to write:")
for key, value in test_task_data.items():
    print(f"      {key}: {value}")
print()

try:
    print(f"   🔧 Getting tasks collection reference...")
    tasks_ref = db.collection('users').document(USER_ID).collection('tasks')
    print(f"   ✅ Tasks ref: {tasks_ref}")

    print(f"   🔧 Creating new task document...")
    task_ref = tasks_ref.document()  # Auto-generate ID
    print(f"   ✅ Task ref: {task_ref}")
    print(f"   ✅ Task ID: {task_ref.id}")
    print(f"   ✅ Task path: {task_ref.path}")

    print(f"   🔧 Writing task data to Firestore...")
    write_result = task_ref.set(test_task_data)
    print(f"   ✅ Write result: {write_result}")
    print(f"   ✅ Write timestamp: {write_result.update_time}")

    print()
    print(f"   ⏳ Waiting 2 seconds for write to propagate...")
    time.sleep(2)

    print(f"   🔧 Verifying task was written...")
    written_task = task_ref.get()

    if written_task.exists:
        print(f"   ✅✅✅ SUCCESS! Task EXISTS in Firestore!")
        written_data = written_task.to_dict()
        print(f"   📊 Written task data:")
        for key, value in written_data.items():
            print(f"      {key}: {value}")
    else:
        print(f"   ❌❌❌ FAILURE! Task DOES NOT EXIST after write!")
        print(f"   🔍 This suggests a write permission issue or path problem")

except Exception as e:
    print(f"   ❌ FAILED to write task: {e}")
    print(f"   🔍 Exception type: {type(e).__name__}")
    traceback.print_exc()
    print()
    print("   💡 This exception is the root cause of the problem!")
print()

# Test 7: List all tasks again to verify
print(f"7️⃣  Listing all tasks after write...")
try:
    tasks_ref = db.collection('users').document(USER_ID).collection('tasks')
    all_tasks = list(tasks_ref.stream())
    print(f"   📊 Total tasks now: {len(all_tasks)}")

    if all_tasks:
        print("   📋 All tasks:")
        for task in all_tasks:
            task_data = task.to_dict()
            is_test = "🧪 TEST" if task_data.get('test_task') else "   "
            print(f"      {is_test} - {task.id}: {task_data.get('name', 'NO NAME')}")
    else:
        print("   ❌ Still no tasks found!")
except Exception as e:
    print(f"   ❌ FAILED to list tasks: {e}")
    traceback.print_exc()
print()

# Test 8: Test using FirebaseClient class
print(f"8️⃣  Testing FirebaseClient class...")
try:
    from utils.firebase_client import FirebaseClient

    print("   🔧 Creating FirebaseClient instance...")
    client = FirebaseClient()
    print(f"   ✅ FirebaseClient created")
    print(f"   📊 client.db: {client.db}")
    print(f"   📊 client.db type: {type(client.db)}")

    if client.db is None:
        print("   ❌❌❌ CRITICAL: client.db is None!")
        print("   🔍 Firebase client not properly initialized")
    else:
        print("   ✅ client.db is properly initialized")

        print()
        print("   🔧 Testing create_task method...")
        result = client.create_task(
            task_name="TEST via FirebaseClient " + datetime.now().strftime("%H:%M:%S"),
            folder_name="daily_tasks",
            user_id=USER_ID,
            recurrence="once"
        )
        print(f"   📊 create_task result: {result}")

        print()
        print("   ⏳ Waiting 2 seconds...")
        time.sleep(2)

        print("   🔧 Verifying task in Firestore...")
        tasks_ref = db.collection('users').document(USER_ID).collection('tasks')
        all_tasks = list(tasks_ref.stream())
        print(f"   📊 Total tasks after FirebaseClient.create_task: {len(all_tasks)}")

        # Find the task we just created
        found = False
        for task in all_tasks:
            task_data = task.to_dict()
            if 'TEST via FirebaseClient' in task_data.get('name', ''):
                print(f"   ✅✅✅ Found task created via FirebaseClient!")
                print(f"      Task ID: {task.id}")
                print(f"      Task name: {task_data.get('name')}")
                found = True
                break

        if not found:
            print(f"   ❌ Task created via FirebaseClient NOT found in Firestore!")

except Exception as e:
    print(f"   ❌ FAILED FirebaseClient test: {e}")
    traceback.print_exc()
print()

print("=" * 80)
print("TEST COMPLETE")
print("=" * 80)
print()
print("📋 SUMMARY:")
print("   1. Check if all tests passed ✅")
print("   2. If Test 6 failed, there's a write permission or path issue")
print("   3. If Test 8 failed, FirebaseClient.create_task has a bug")
print("   4. Check Firebase Console at:")
print(f"      https://console.firebase.google.com/project/voicelog-ai-dc521/firestore")
print(f"      Path: users/{USER_ID}/tasks/")
print()
