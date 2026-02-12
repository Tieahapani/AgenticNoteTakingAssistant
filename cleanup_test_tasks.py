#!/usr/bin/env python3
"""
Cleanup test tasks created during debugging.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.firebase_client import FirebaseClient

USER_ID = "gXLno2jNqIP0hTkV7g6zFQCutf83"

print(f"\n{'='*80}")
print(f"🧹 CLEANING UP TEST TASKS")
print(f"{'='*80}\n")

# Initialize Firebase client
client = FirebaseClient()

# Get all tasks
tasks_ref = client._get_user_tasks_ref(USER_ID)
all_tasks = list(tasks_ref.stream())

deleted_count = 0

for task in all_tasks:
    task_data = task.to_dict()

    # Delete if it's marked as a test task
    if task_data.get('test_task'):
        print(f"🗑️  Deleting test task: {task_data.get('name')}")
        task.reference.delete()
        deleted_count += 1

print(f"\n✅ Deleted {deleted_count} test task(s)")
print(f"{'='*80}\n")
