# test_firebase_query.py

import firebase_admin
from firebase_admin import credentials, firestore
import json

# Initialize Firebase
cred = credentials.Certificate("firebase-credentials.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

user_id = "gXLno2jNqIP0hTkV7g6zFQCutf83"

print(f"\n{'='*60}")
print(f"QUERYING FIREBASE FOR USER: {user_id}")
print(f"{'='*60}\n")

# 1. Check folders
print("📁 FOLDERS:")
folders_ref = db.collection('users').document(user_id).collection('folders')
folders = list(folders_ref.stream())

if folders:
    for folder in folders:
        folder_data = folder.to_dict()
        print(f"  ✅ {folder.id}")
        print(f"     name: {folder_data.get('name')}")
        print(f"     emoji: {folder_data.get('emoji')}")
        print()
else:
    print("  ❌ No folders found\n")

# 2. Check tasks (with ALL fields)
print("📋 TASKS:")
tasks_ref = db.collection('users').document(user_id).collection('tasks')
tasks = list(tasks_ref.stream())

if tasks:
    for task in tasks:
        task_data = task.to_dict()
        print(f"  ✅ Task ID: {task.id}")
        print(f"     name: {task_data.get('name')}")
        print(f"     folder: {task_data.get('folder')}")
        print(f"     completed: {task_data.get('completed')}")
        print(f"     recurrence: {task_data.get('recurrence')}")
        print(f"     time: {task_data.get('time')}")
        print(f"     duration: {task_data.get('duration')}")
        print(f"     due_date: {task_data.get('due_date')}")
        print(f"     is_high_priority: {task_data.get('is_high_priority')}")
        print(f"     created_at: {task_data.get('created_at')}")
        print(f"     completed_at: {task_data.get('completed_at')}")
        print()
else:
    print("  ❌ No tasks found\n")

print(f"{'='*60}")
print(f"SUMMARY:")
print(f"  Folders: {len(folders)}")
print(f"  Tasks: {len(tasks)}")
print(f"{'='*60}\n")