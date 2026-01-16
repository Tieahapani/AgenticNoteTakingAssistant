# fix_timezone_data.py

from utils.firebase_client import FirebaseClient
from datetime import datetime
import pytz

print("🔧 Fixing timezone data in Firebase...")
print("-" * 60)

fb = FirebaseClient()
ist = pytz.timezone('Asia/Kolkata')

tasks = fb.db.collection('tasks').where('completed', '==', True).stream()

fixed_count = 0

for task in tasks:
    data = task.to_dict()
    
    if data.get('completed_at'):
        try:
            # Parse the UTC timestamp
            if isinstance(data['completed_at'], str):
                dt_utc = datetime.fromisoformat(data['completed_at'].replace('Z', '+00:00'))
            else:
                dt_utc = datetime.fromtimestamp(data['completed_at'].timestamp(), tz=pytz.UTC)
            
            # Convert to IST
            dt_ist = dt_utc.astimezone(ist)
            
            # Update with correct IST hour and day
            old_hour = data.get('completed_hour')
            new_hour = dt_ist.hour
            new_day = dt_ist.strftime('%A')
            
            task.reference.update({
                'completed_hour': new_hour,
                'completed_day': new_day
            })
            
            print(f"✅ {data['name']}")
            print(f"   Old: hour={old_hour}")
            print(f"   New: hour={new_hour} ({dt_ist.strftime('%I:%M %p IST')}), day={new_day}")
            
            fixed_count += 1
            
        except Exception as e:
            print(f"❌ Error fixing {data['name']}: {e}")

print("-" * 60)
print(f"✅ Fixed {fixed_count} tasks!")