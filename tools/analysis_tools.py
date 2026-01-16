from langchain_core.tools import tool
from datetime import datetime, timedelta
from collections import defaultdict
import pytz
import inspect

try:
    from zoneinfo import ZoneInfo
except ImportError:
    import pytz


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_user_id_from_context():
    """Extract user_id from execution context"""
    frame = inspect.currentframe()
    try:
        while frame:
            if 'config' in frame.f_locals:
                config = frame.f_locals['config']
                if isinstance(config, dict) and 'configurable' in config:
                    return config['configurable']['user_id']
            frame = frame.f_back
        raise Exception("Could not find user_id in execution context")
    finally:
        del frame


def _get_tz(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return pytz.timezone(tz_name)


def _parse_utc_iso(dt_str: str):
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except Exception:
        return None


def _to_local(dt_utc: datetime, user_timezone: str):
    return dt_utc.astimezone(_get_tz(user_timezone))


# =========================================================
# PRODUCTIVITY PATTERNS
# =========================================================

@tool
def get_productivity_patterns(user_timezone: str) -> dict:
    """
    Return structured productivity facts.
    NO prose. NO formatting.
    """
    from utils.firebase_client import FirebaseClient
    
    user_id = get_user_id_from_context()
    client = FirebaseClient()

    tasks = client.get_all_tasks(user_id)
    completed = [t for t in tasks if t.get("completed")]
    incomplete = [t for t in tasks if not t.get("completed")]

    if not completed:
        return {"has_data": False}

    hour_counts = defaultdict(int)
    day_counts = defaultdict(int)

    for task in completed:
        dt_utc = _parse_utc_iso(task.get("completed_at"))
        if not dt_utc:
            continue
        dt_local = _to_local(dt_utc, user_timezone)
        hour_counts[dt_local.hour] += 1
        day_counts[dt_local.strftime("%A")] += 1
    print("DAY COUNTS (local time):", dict(day_counts))

    peak_hour_24, peak_hour_count = max(hour_counts.items(), key=lambda x: x[1])
    peak_day, peak_day_count = max(day_counts.items(), key=lambda x: x[1])

    durations = []
    for task in completed:
        created = _parse_utc_iso(task.get("created_at"))
        completed_at = _parse_utc_iso(task.get("completed_at"))
        if created and completed_at:
            durations.append((completed_at - created).total_seconds() / 3600)

    avg_completion_hours = (
        round(sum(durations) / len(durations), 2) if durations else None
    )

    high_priority = [t for t in tasks if t.get("is_high_priority")]
    hp_completed = [t for t in high_priority if t.get("completed")]

    hp_completion_rate = (
        round((len(hp_completed) / len(high_priority)) * 100, 1)
        if high_priority else None
    )

    now_local = _to_local(datetime.now(pytz.UTC), user_timezone)
    overdue_count = 0

    for task in incomplete:
        created_utc = _parse_utc_iso(task.get("created_at"))
        if not created_utc:
            continue
        created_local = _to_local(created_utc, user_timezone)
        age_days = (now_local.date() - created_local.date()).days
        if age_days >= 3:
            overdue_count += 1

    return {
        "has_data": True,
        "peak_hour_24": peak_hour_24,
        "peak_hour_count": peak_hour_count,
        "peak_day": peak_day,
        "peak_day_count": peak_day_count,
        "avg_completion_hours": avg_completion_hours,
        "high_priority_completion_rate": hp_completion_rate,
        "overdue_task_count": overdue_count,
        "timezone_used": user_timezone,
    }


# =========================================================
# PROCRASTINATION / AVOIDANCE
# =========================================================

@tool
def get_procrastination_report(user_timezone: str) -> dict:
    """
    Return structured data about delayed / avoided tasks.
    """
    from utils.firebase_client import FirebaseClient
    
    user_id = get_user_id_from_context()
    client = FirebaseClient()

    tasks = client.get_all_tasks(user_id)
    incomplete = [t for t in tasks if not t.get("completed")]

    if not incomplete:
        return {"has_data": False}

    now_local = _to_local(datetime.now(pytz.UTC), user_timezone)
    analyzed = []

    for task in incomplete:
        created_utc = _parse_utc_iso(task.get("created_at"))
        if not created_utc:
            continue

        created_local = _to_local(created_utc, user_timezone)
        age_days = (now_local.date() - created_local.date()).days

        analyzed.append({
            "name": task.get("name"),
            "folder": task.get("folder"),
            "age_days": age_days,
            "is_high_priority": task.get("is_high_priority", False)
        })

    analyzed.sort(key=lambda x: x["age_days"], reverse=True)

    return {
        "has_data": True,
        "total_pending": len(analyzed),
        "high_priority_pending": sum(1 for t in analyzed if t["is_high_priority"]),
        "oldest_task_days": analyzed[0]["age_days"] if analyzed else None,
        "tasks": analyzed[:10],  # top 10 only
        "timezone_used": user_timezone,
    }


# =========================================================
# WEEKLY ACCOUNTABILITY
# =========================================================

@tool
def get_weekly_accountability_summary(user_timezone: str) -> dict:
    """
    Return structured weekly productivity data.
    """
    from utils.firebase_client import FirebaseClient
    
    user_id = get_user_id_from_context()
    client = FirebaseClient()

    now_utc = datetime.now(pytz.UTC)
    now_local = _to_local(now_utc, user_timezone)
    week_ago_local = now_local - timedelta(days=7)
    week_ago_utc = week_ago_local.astimezone(pytz.UTC)

    tasks = client.get_all_tasks(user_id)

    created = []
    completed = []

    for task in tasks:
        created_dt = _parse_utc_iso(task.get("created_at"))
        completed_dt = _parse_utc_iso(task.get("completed_at"))

        if created_dt and created_dt >= week_ago_utc:
            created.append(task)

        if completed_dt and completed_dt >= week_ago_utc:
            completed.append(task)

    completion_rate = (
        round(
            sum(1 for t in created if t.get("completed")) / len(created) * 100,
            1
        ) if created else None
    )

    return {
        "has_data": True,
        "week_start_local": week_ago_local.date().isoformat(),
        "week_end_local": now_local.date().isoformat(),
        "tasks_created": len(created),
        "tasks_completed": len(completed),
        "completion_rate": completion_rate,
        "timezone_used": user_timezone,
    }


# =========================================================
# FOLDER FOCUS (NO TIME MATH, BUT CONSISTENT SIGNATURE)
# =========================================================

@tool
def get_folder_focus_summary(user_timezone: str) -> dict:
    """
    Return structured data about folder usage.
    Timezone not used, but required for consistency.
    """
    from utils.firebase_client import FirebaseClient
    
    user_id = get_user_id_from_context()
    client = FirebaseClient()

    tasks = client.get_all_tasks(user_id)
    if not tasks:
        return {"has_data": False}

    folder_total = defaultdict(int)
    folder_completed = defaultdict(int)

    for task in tasks:
        folder = task.get("folder", "uncategorized")
        folder_total[folder] += 1
        if task.get("completed"):
            folder_completed[folder] += 1

    most_created = max(folder_total.items(), key=lambda x: x[1])
    most_completed = (
        max(folder_completed.items(), key=lambda x: x[1])
        if folder_completed else (None, 0)
    )

    return {
        "has_data": True,
        "most_created_folder": most_created[0],
        "most_created_count": most_created[1],
        "most_completed_folder": most_completed[0],
        "most_completed_count": most_completed[1],
        "timezone_used": user_timezone,
    }


@tool
def get_tasks_by_filter(
    user_timezone: str,
    completed: bool | None = None,
    is_high_priority: bool | None = None,
    hour: int | None = None
) -> dict:
    """
    Return task names filtered by simple criteria.

    This tool returns DATA ONLY.
    No prose. No interpretation.

    Args:
        user_timezone: User's timezone (e.g. "Asia/Kolkata")
        completed: True / False / None
        is_high_priority: True / False / None
        hour: Local hour (0–23) tasks were completed at
    """
    from utils.firebase_client import FirebaseClient
    
    user_id = get_user_id_from_context()
    client = FirebaseClient()
    
    tasks = client.get_all_tasks(user_id)

    results = []

    for task in tasks:
        # --------------------
        # Completed filter
        # --------------------
        if completed is not None and task.get("completed") != completed:
            continue

        # --------------------
        # High priority filter
        # --------------------
        if is_high_priority is not None and task.get("is_high_priority") != is_high_priority:
            continue

        # --------------------
        # Hour filter (only applies to completed tasks)
        # --------------------
        if hour is not None:
            completed_at = task.get("completed_at")
            if not completed_at:
                continue

            dt_utc = _parse_utc_iso(completed_at)
            if not dt_utc:
                continue

            dt_local = dt_utc.astimezone(ZoneInfo(user_timezone))
            if dt_local.hour != hour:
                continue

        results.append({
            "name": task.get("name"),
            "folder": task.get("folder"),
            "is_high_priority": task.get("is_high_priority", False),
            "completed": task.get("completed", False),
        })

    return {
        "has_data": True,
        "task_count": len(results),
        "tasks": results[:15],  # cap for safety
        "timezone_used": user_timezone
    }