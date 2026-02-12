#!/usr/bin/env python3
"""
List all tasks in Firestore for a specific user.
This shows EXACTLY what's in your Firebase database.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.firebase_client import FirebaseClient

# Your user ID
USER_ID = "gXLno2jNqIP0hTkV7g6zFQCutf83"

print(f"\n{'='*80}")
print(f"📊 LISTING ALL TASKS IN FIRESTORE")
print(f"{'='*80}")
print(f"👤 User ID: {USER_ID}")
print(f"📍 Firestore path: users/{USER_ID}/tasks/")
print(f"{'='*80}\n")

# Initialize Firebase client
client = FirebaseClient()

# Get all tasks
tasks_ref = client._get_user_tasks_ref(USER_ID)
all_tasks = list(tasks_ref.stream())

print(f"📊 Total tasks found: {len(all_tasks)}\n")

if not all_tasks:
    print("❌ No tasks found in Firestore!")
    print("\nThis means:")
    print("  1. Tasks aren't being written, OR")
    print("  2. You're using a different user_id in your app")
else:
    print(f"✅ Found {len(all_tasks)} tasks:\n")

    for i, task in enumerate(all_tasks, 1):
        task_data = task.to_dict()

        print(f"{i}. Task ID: {task.id}")
        print(f"   Path: {task.reference.path}")
        print(f"   Name: {task_data.get('name', 'NO NAME')}")
        print(f"   Folder: {task_data.get('folder', 'NO FOLDER')}")
        print(f"   Completed: {'✅' if task_data.get('completed') else '⭕'}")
        print(f"   Created: {task_data.get('created_at')}")

        # Show if this is a test task
        if task_data.get('test_task'):
            print(f"   🧪 TEST TASK (safe to delete)")

        print()

print(f"{'='*80}")
print(f"🔗 FIREBASE CONSOLE URL:")
print(f"{'='*80}")
print(f"https://console.firebase.google.com/project/voicelog-ai-dc521/firestore/databases/-default-/data/~2Fusers~2F{USER_ID}~2Ftasks")
print(f"\nNote: Firestore subcollections don't show up unless they have documents!")
print(f"If you see tasks above, they ARE in your Firestore.\n")
