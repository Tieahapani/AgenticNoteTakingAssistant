# backend/agents/monitor_service.py

from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from monitor_agent import MonitorAgent
from cleanup_agents import CleanupAgent

def run_monitor_check(check_type="scheduled"):
    """Execute monitor analysis"""
    print("\n" + "="*70)
    print(f"⏰ {check_type.upper()} MONITOR CHECK at {datetime.now()}")
    print("="*70 + "\n")
    
    try:
        monitor = MonitorAgent()
        monitor.run(
            user_id="default_user",
            user_timezone="Asia/Kolkata",
            socketio=None
        )
    except Exception as e:
        print(f"❌ Monitor failed: {e}")
        import traceback
        traceback.print_exc()

def run_cleanup_check():
    """Execute cleanup agent - runs weekly"""
    print("\n" + "="*70)
    print(f"🧹 WEEKLY CLEANUP CHECK at {datetime.now()}")
    print("="*70 + "\n")
    
    try:
        cleanup = CleanupAgent()
        cleanup.run(
            user_id="default_user",
            user_timezone="Asia/Kolkata",  # ← Passed to cleanup agent
            socketio=None
        )
    except Exception as e:
        print(f"❌ Cleanup failed: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Start the scheduler"""
    print("🚀 Starting Monitor & Cleanup Service...")
    print("\n📅 Schedule:")
    print("   MONITOR:")
    print("   - Morning Digest: 7:00 AM daily")
    print("   - Midday Check: 12:00 PM daily")
    print("   - Evening Summary: 8:00 PM daily")
    print("\n   CLEANUP:")
    print("   - Weekly Cleanup: Sunday 9:00 PM")
    print("\nPress Ctrl+C to stop\n")
    
    scheduler = BlockingScheduler()
    
    # Morning digest
    scheduler.add_job(
        run_monitor_check,
        trigger=CronTrigger(hour=7, minute=0),
        args=['morning'],
        id='morning_digest'
    )
    
    # Midday check
    scheduler.add_job(
        run_monitor_check,
        trigger=CronTrigger(hour=12, minute=0),
        args=['midday'],
        id='midday_check'
    )
    
    # Evening summary
    scheduler.add_job(
        run_monitor_check,
        trigger=CronTrigger(hour=20, minute=0),
        args=['evening'],
        id='evening_summary'
    )
    
    # Weekly cleanup (Sunday 9 PM)
    scheduler.add_job(
        run_cleanup_check,
        trigger=CronTrigger(day_of_week='sun', hour=21, minute=0),
        id='weekly_cleanup'
    )
    
    print("🔄 Running initial monitor check...")
    run_monitor_check('startup')
    
    print(f"\n✅ Scheduler started")
    print("⏰ Next monitor: 7:00 AM tomorrow")
    print("🧹 Next cleanup: Sunday 9:00 PM\n")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 Service stopped")

if __name__ == "__main__":
    main()