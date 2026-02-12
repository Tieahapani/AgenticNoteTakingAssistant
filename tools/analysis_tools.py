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

    # Weighted scoring: high priority = 3, has deadline = 2, regular = 1
    def _task_weight(t):
        if t.get("is_high_priority"):
            return 3
        if t.get("due_date") and str(t.get("due_date", "")).strip():
            return 2
        return 1

    # Time-of-day bucketing
    def _time_bucket(hour):
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"

    hour_scores = defaultdict(float)
    day_scores = defaultdict(float)
    hour_counts = defaultdict(int)
    day_counts = defaultdict(int)
    bucket_scores = defaultdict(float)

    for task in completed:
        w = _task_weight(task)

        # --- Day: prefer stored completed_day (safety net), fall back to timestamp ---
        stored_day = task.get("completed_day")
        if stored_day and isinstance(stored_day, str) and stored_day.strip():
            day = stored_day.strip()
        else:
            dt_utc = _parse_utc_iso(task.get("completed_at"))
            if not dt_utc:
                continue
            day = _to_local(dt_utc, user_timezone).strftime("%A")

        day_scores[day] += w
        day_counts[day] += 1

        # --- Hour: derive from completed_at timestamp (need local conversion) ---
        dt_utc = _parse_utc_iso(task.get("completed_at"))
        if dt_utc:
            local_hour = _to_local(dt_utc, user_timezone).hour
            hour_scores[local_hour] += w
            hour_counts[local_hour] += 1
            bucket_scores[_time_bucket(local_hour)] += w

    print("DAY SCORES (weighted):", dict(day_scores))
    print("DAY COUNTS (raw):", dict(day_counts))
    print("HOUR SCORES (weighted):", dict(hour_scores))
    print("BUCKET SCORES:", dict(bucket_scores))

    if not day_scores:
        return {
            "has_data": False,
            "reason": "Completed tasks exist but none have valid timestamps or stored day.",
        }

    # --- Detect ties / insufficient data ---
    # Peak day: only report if the top day clearly leads (score > second place)
    sorted_days = sorted(day_scores.items(), key=lambda x: x[1], reverse=True)
    top_day, top_day_score = sorted_days[0]
    second_day_score = sorted_days[1][1] if len(sorted_days) > 1 else 0

    if top_day_score > second_day_score:
        peak_day = top_day
        peak_day_count = day_counts[top_day]
    else:
        # Tie — not enough data to determine a clear peak
        peak_day = None
        peak_day_count = None

    # Peak hour: same tie detection
    peak_hour_24 = None
    peak_hour_count = None
    peak_bucket = None
    if hour_scores:
        sorted_hours = sorted(hour_scores.items(), key=lambda x: x[1], reverse=True)
        top_hour, top_hour_score = sorted_hours[0]
        second_hour_score = sorted_hours[1][1] if len(sorted_hours) > 1 else 0

        if top_hour_score > second_hour_score:
            peak_hour_24 = top_hour
            peak_hour_count = hour_counts[top_hour]

    if bucket_scores:
        sorted_buckets = sorted(bucket_scores.items(), key=lambda x: x[1], reverse=True)
        top_bucket, top_bucket_score = sorted_buckets[0]
        second_bucket_score = sorted_buckets[1][1] if len(sorted_buckets) > 1 else 0

        if top_bucket_score > second_bucket_score:
            peak_bucket = top_bucket

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
        due_date_str = task.get("due_date", "")
        if due_date_str and due_date_str.strip():
            try:
                due = datetime.strptime(due_date_str.strip(), "%Y-%m-%d").date()
                if due < now_local.date():
                    overdue_count += 1
            except ValueError:
                pass
        else:
            created_utc = _parse_utc_iso(task.get("created_at"))
            if not created_utc:
                continue
            created_local = _to_local(created_utc, user_timezone)
            age_days = (now_local.date() - created_local.date()).days
            if age_days >= 7:
                overdue_count += 1

    return {
        "has_data": True,
        "total_completed": len(completed),
        "peak_hour_24": peak_hour_24,
        "peak_hour_count": peak_hour_count,
        "peak_time_of_day": peak_bucket,
        "peak_day": peak_day,
        "peak_day_count": peak_day_count,
        "scoring_note": "weighted: high_priority=3x, has_deadline=2x, regular=1x. null means tied/not enough data.",
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

    today = now_local.date()
    overdue_count = 0

    for task in incomplete:
        created_utc = _parse_utc_iso(task.get("created_at"))
        if not created_utc:
            continue

        created_local = _to_local(created_utc, user_timezone)
        age_days = (now_local.date() - created_local.date()).days

        # Check actual due_date for overdue status
        due_date_str = task.get("due_date", "")
        is_overdue = False
        days_overdue = None
        if due_date_str and due_date_str.strip():
            try:
                due = datetime.strptime(due_date_str.strip(), "%Y-%m-%d").date()
                if due < today:
                    is_overdue = True
                    days_overdue = (today - due).days
            except ValueError:
                pass

        if is_overdue:
            overdue_count += 1

        analyzed.append({
            "name": task.get("name"),
            "folder": task.get("folder"),
            "age_days": age_days,
            "is_high_priority": task.get("is_high_priority", False),
            "due_date": due_date_str or None,
            "is_overdue": is_overdue,
            "days_overdue": days_overdue,
        })

    # Sort: overdue first, then by age
    analyzed.sort(key=lambda x: (not x["is_overdue"], -(x["days_overdue"] or 0), -x["age_days"]))

    return {
        "has_data": True,
        "total_pending": len(analyzed),
        "high_priority_pending": sum(1 for t in analyzed if t["is_high_priority"]),
        "overdue_count": overdue_count,
        "oldest_task_days": max((t["age_days"] for t in analyzed), default=None),
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
    hour: int | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    overdue_only: bool = False,
) -> dict:
    """
    Return tasks with timestamps filtered by simple criteria.

    This tool returns DATA ONLY including when tasks were created/completed.
    No prose. No interpretation.

    Args:
        user_timezone: User's timezone (e.g. "America/Los Angeles")
        completed: True / False / None
        is_high_priority: True / False / None
        hour: Local hour (0–23) tasks were completed at
        due_before: Only tasks with due_date on or before this date (YYYY-MM-DD)
        due_after: Only tasks with due_date on or after this date (YYYY-MM-DD)
        overdue_only: If True, only return incomplete tasks whose due_date is before today

    Returns:
        Dict with tasks including name, folder, completed status,
        created_at, completed_at, and due_date.
    """
    from utils.firebase_client import FirebaseClient

    user_id = get_user_id_from_context()
    client = FirebaseClient()

    tasks = client.get_all_tasks(user_id)

    # Pre-parse date filter boundaries
    now_local = _to_local(datetime.now(pytz.UTC), user_timezone)
    today = now_local.date()

    def _parse_date(s):
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d").date()
        except (ValueError, AttributeError):
            return None

    due_before_date = _parse_date(due_before) if due_before else None
    due_after_date = _parse_date(due_after) if due_after else None

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

        # --------------------
        # Due date filters
        # --------------------
        task_due_str = task.get("due_date", "")
        task_due = _parse_date(task_due_str) if task_due_str else None

        if due_before_date is not None:
            if task_due is None or task_due > due_before_date:
                continue

        if due_after_date is not None:
            if task_due is None or task_due < due_after_date:
                continue

        if overdue_only:
            if task.get("completed"):
                continue
            if task_due is None or task_due >= today:
                continue

        results.append({
            "name": task.get("name"),
            "folder": task.get("folder"),
            "is_high_priority": task.get("is_high_priority", False),
            "completed": task.get("completed", False),
            "created_at": task.get("created_at"),
            "completed_at": task.get("completed_at"),
            "due_date": task.get("due_date"),
        })

    return {
        "has_data": True,
        "task_count": len(results),
        "tasks": results[:15],  # cap for safety
        "timezone_used": user_timezone
    }