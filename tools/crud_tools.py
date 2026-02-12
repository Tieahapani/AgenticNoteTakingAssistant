from langchain_core.tools import tool
from utils.firebase_client import FirebaseClient
from datetime import datetime
import pytz
import re
import inspect

firebase_client = FirebaseClient()


# ============================================
# HELPER FUNCTION TO GET USER_ID
# ============================================

def get_user_id_from_context():
    """
    Extract user_id from the execution context.
    LangGraph passes config through the call stack.
    """
    frame = inspect.currentframe()
    try:
        # Walk up the stack to find config
        while frame:
            if 'config' in frame.f_locals:
                config = frame.f_locals['config']
                if isinstance(config, dict) and 'configurable' in config:
                    return config['configurable']['user_id']
            frame = frame.f_back
        
        # Fallback - should never happen in production
        raise Exception("Could not find user_id in execution context")
    finally:
        del frame


# ============================================
# CREATE OPERATIONS
# ============================================

@tool 
def create_folder(folder_name: str, emoji: str = "") -> str: 
    """Create a new folder for organizing tasks.
    
    Args:
        folder_name: Name of the folder (e.g., "Work", "Personal")
        emoji: Optional emoji for the folder (e.g., "💼", "🏠")
    """
    user_id = get_user_id_from_context()
    result = firebase_client.create_folder(folder_name.strip().title(), emoji.strip(), user_id)
    return result


@tool 
def create_task(
    task_name: str, 
    folder_name: str, 
    duration: str = "", 
    due_date: str = "",
    recurrence: str = "", 
    time: str = ""
) -> str: 
    """Create a new task in a folder.
    
    Args:
        task_name: Name of the task
        folder_name: Folder to put task in (e.g., "Work", "Personal", "School")
        duration: How long the task takes (e.g., "30 minutes", "1 hour")
        due_date: Due date in YYYY-MM-DD format (MUST be from date tool, not calculated)
        recurrence: "once", "daily", "weekly" (default: "once")
        time: When to do the task (optional, e.g., "9:00 AM")
    
    CRITICAL: due_date MUST come from a date tool (get_next_weekday, get_date_in_days, etc.)
    NEVER pass strings like "tomorrow" or "next Monday" - they will be rejected.
    NEVER calculate dates yourself - you will hallucinate wrong years like 2022.
    
    Examples:
        User says "task due next Monday"
        Step 1: Call get_next_weekday("Monday") → returns "2026-02-10"
        Step 2: Call create_task(task_name="Task", folder_name="work", due_date="2026-02-10")
    """
    user_id = get_user_id_from_context()

    # Validate due_date format — reject anything that isn't YYYY-MM-DD
    if due_date and due_date.strip():
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", due_date.strip()):
            return (
                f"ERROR: due_date '{due_date}' is not in YYYY-MM-DD format. "
                "You MUST call a date tool first (get_next_weekday, get_date_in_days, "
                "parse_relative_date) and use the YYYY-MM-DD value from its output."
            )

    result = firebase_client.create_task(
        task_name=task_name,
        folder_name=folder_name,
        user_id=user_id,
        recurrence=recurrence,
        time=time,
        duration=duration,
        due_date=due_date
    )

    return result
        

# ============================================
# OPERATIONS WITH FUZZY MATCHING
# ============================================

@tool
def mark_task_complete(task_description: str) -> str:
    """
    Mark a task as complete using natural language.
    You don't need the exact task name - describe it naturally.
    
    Examples:
    - "30 pounds shoulder" will find "Shoulder Press 30lbs"
    - "woke up" will find "Wake up at 5:45 AM"
    - "morning workout" will find the workout task
    
    Args:
        task_description: How you describe the task (natural language)
    """
    from utils.intent_resolver import intent_resolver
    
    user_id = get_user_id_from_context()
    
    # Only search incomplete tasks (can't complete what's already done)
    match = intent_resolver.resolve_task_name(task_description, only_incomplete=True, user_id=user_id)
    
    if not match:
        # No match - show suggestions (only incomplete tasks)
        suggestions = intent_resolver.get_task_suggestions(task_description, only_incomplete=True, user_id=user_id)
        if suggestions:
            suggestion_list = "\n".join([
                f"  • {s['name']} ({'✅' if s['completed'] else '⭕'})"
                for s in suggestions
            ])
            return f"❌ Couldn't find '{task_description}'.\n\nDid you mean:\n{suggestion_list}"
        else:
            return f"No incomplete tasks found matching '{task_description}'"
    
    # Found a match - execute
    result = firebase_client.mark_task_complete(match['exact_name'], user_id)
    
    confidence_msg = f" (matched with {match['confidence']:.0%} confidence)" if match['confidence'] < 0.9 else ""
    
    return f"✅ {result}{confidence_msg}"


@tool
def mark_task_incomplete(task_description: str) -> str:
    """
    Mark a task as incomplete using natural language.
    
    Args:
        task_description: How you describe the task
    """
    from utils.intent_resolver import intent_resolver
    
    user_id = get_user_id_from_context()
    
    # Search ALL tasks (need to find completed ones to mark incomplete)
    match = intent_resolver.resolve_task_name(task_description, only_incomplete=False, user_id=user_id)
    
    if not match:
        # No match - show suggestions
        suggestions = intent_resolver.get_task_suggestions(task_description, only_incomplete=False, user_id=user_id)
        if suggestions:
            suggestion_list = "\n".join([f"  • {s['name']}" for s in suggestions])
            return f"❌ Couldn't find '{task_description}'.\n\nDid you mean:\n{suggestion_list}"
        return f"No tasks found matching '{task_description}'"
    
    result = firebase_client.mark_task_incomplete(match['exact_name'], user_id)
    
    return f"✅ {result}"


@tool
def delete_task(task_description: str) -> str:
    """
    Delete a task using natural language.
    
    Args:
        task_description: How you describe the task to delete
    """
    from utils.intent_resolver import intent_resolver
    
    user_id = get_user_id_from_context()
    
    # Search ALL tasks (can delete completed or incomplete)
    match = intent_resolver.resolve_task_name(task_description, only_incomplete=False, user_id=user_id)
    
    if not match:
        # No match - show suggestions
        suggestions = intent_resolver.get_task_suggestions(task_description, only_incomplete=False, user_id=user_id)
        if suggestions:
            suggestion_list = "\n".join([f"  • {s['name']}" for s in suggestions])
            return f"❌ Couldn't find '{task_description}'.\n\nDid you mean:\n{suggestion_list}"
        return f"No tasks found matching '{task_description}'"
    
    result = firebase_client.delete_task(match['exact_name'], user_id)
    
    return f"🗑️ {result}"


@tool
def delete_folder(folder_description: str) -> str:
    """
    Delete a folder using natural language.

    Args:
        folder_description: How you describe the folder
    """
    from utils.intent_resolver import intent_resolver

    user_id = get_user_id_from_context()

    match = intent_resolver.resolve_folder_name(folder_description, user_id=user_id)

    if not match:
        suggestions = intent_resolver.get_folder_suggestions(folder_description, user_id=user_id)
        if suggestions:
            suggestion_list = "\n".join([f"  • {s['emoji']} {s['name']}" for s in suggestions])
            return f"❌ Couldn't find folder matching '{folder_description}'.\n\nAvailable folders:\n{suggestion_list}"
        return f"No folders found matching '{folder_description}'"

    result = firebase_client.delete_folder(match['exact_name'], user_id)

    return f"🗑️ {result}"


@tool
def move_task(task_description: str, destination_folder_description: str) -> str:
    """
    Move a task to another folder using natural language.
    
    Args:
        task_description: The task to move (natural language)
        destination_folder_description: Where to move it (natural language)
    """
    from utils.intent_resolver import intent_resolver
    
    user_id = get_user_id_from_context()
    
    # Search ALL tasks (can move completed or incomplete)
    task_match = intent_resolver.resolve_task_name(task_description, only_incomplete=False, user_id=user_id)
    if not task_match:
        return f"❌ Couldn't find task matching '{task_description}'"
    
    # Resolve folder
    folder_match = intent_resolver.resolve_folder_name(destination_folder_description, user_id=user_id)
    if not folder_match:
        suggestions = intent_resolver.get_folder_suggestions(destination_folder_description, user_id=user_id)
        if suggestions:
            suggestion_list = "\n".join([f"  • {s['emoji']} {s['name']}" for s in suggestions])
            return f"❌ Couldn't find folder matching '{destination_folder_description}'.\n\nAvailable folders:\n{suggestion_list}"
        return f"No folders found matching '{destination_folder_description}'"
    
    result = firebase_client.move_task(task_match['exact_name'], folder_match['exact_name'], user_id)
    
    return f"📦 {result}"


@tool
def edit_task(
    task_description: str,
    new_task_name: str = None,
    new_folder_description: str = None,
    new_recurrence: str = None,
    new_time: str = None,
    new_duration: str = None,
    new_due_date: str = None
) -> str:
    """
    Edit properties of an existing task using natural language.

    Args:
        task_description: Current task (natural language)
        new_task_name: New name for the task (optional)
        new_folder_description: New folder (natural language, optional)
        new_recurrence: New recurrence ("once", "daily", "weekly") (optional)
        new_time: New time for the task (optional)
        new_duration: New duration (optional)
        new_due_date: New due date in YYYY-MM-DD format (MUST be from a date tool, optional)
    """
    from utils.intent_resolver import intent_resolver
    
    user_id = get_user_id_from_context()
    
    # Search ALL tasks (can edit completed or incomplete)
    task_match = intent_resolver.resolve_task_name(task_description, only_incomplete=False, user_id=user_id)
    if not task_match:
        return f"❌ Couldn't find task matching '{task_description}'"
    
    # Validate new_due_date format
    if new_due_date and new_due_date.strip():
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", new_due_date.strip()):
            return (
                f"ERROR: new_due_date '{new_due_date}' is not in YYYY-MM-DD format. "
                "You MUST call a date tool first and use the YYYY-MM-DD value from its output."
            )

    # Resolve new folder if specified
    new_folder_exact = None
    if new_folder_description:
        folder_match = intent_resolver.resolve_folder_name(new_folder_description, user_id=user_id)
        if folder_match:
            new_folder_exact = folder_match['exact_name']
        else:
            return f"❌ Couldn't find folder matching '{new_folder_description}'"

    result = firebase_client.edit_task(
        old_task_name=task_match['exact_name'],
        new_task_name=new_task_name,
        new_folder=new_folder_exact,
        new_recurrence=new_recurrence,
        new_time=new_time,
        new_duration=new_duration,
        new_due_date=new_due_date,
        user_id=user_id
    )
    
    return f"✏️ {result}"


@tool
def edit_folder_name(old_folder_description: str, new_name: str, new_emoji: str = None) -> str:
    """
    Rename a folder using natural language.
    
    Args:
        old_folder_description: Current folder (natural language)
        new_name: New folder name
        new_emoji: New emoji (optional)
    """
    from utils.intent_resolver import intent_resolver
    
    user_id = get_user_id_from_context()
    
    match = intent_resolver.resolve_folder_name(old_folder_description, user_id=user_id)
    
    if not match:
        suggestions = intent_resolver.get_folder_suggestions(old_folder_description, user_id=user_id)
        if suggestions:
            suggestion_list = "\n".join([f"  • {s['emoji']} {s['name']}" for s in suggestions])
            return f"❌ Couldn't find folder matching '{old_folder_description}'.\n\nAvailable folders:\n{suggestion_list}"
        return f"No folders found matching '{old_folder_description}'"
    
    result = firebase_client.edit_folder_name(
        old_name=match['exact_name'],
        new_name=new_name,
        new_emoji=new_emoji,
        user_id=user_id
    )
    
    return f"✏️ {result}"


@tool
def get_folder_contents(folder_description: str) -> str:
    """
    List all tasks in a specific folder using natural language.
    
    Examples:
    - "workout stuff" → finds "Health" folder
    - "work things" → finds "Work" folder
    
    Args:
        folder_description: How you describe the folder (natural language)
    """
    from utils.intent_resolver import intent_resolver
    
    user_id = get_user_id_from_context()
    
    # Resolve folder
    match = intent_resolver.resolve_folder_name(folder_description, user_id=user_id)
    
    if not match:
        suggestions = intent_resolver.get_folder_suggestions(folder_description, user_id=user_id)
        if suggestions:
            suggestion_list = "\n".join([f"  • {s['emoji']} {s['name']}" for s in suggestions])
            return f"❌ Couldn't find folder matching '{folder_description}'.\n\nAvailable folders:\n{suggestion_list}"
        return f"No folders found matching '{folder_description}'"
    
    result = firebase_client.get_folder_contents(match['exact_name'], user_id)
    
    return result


# ============================================
# UTILITY OPERATIONS
# ============================================

@tool 
def list_all_folders() -> str:
    """List all folders in the system."""
    user_id = get_user_id_from_context()
    result = firebase_client.list_all_folders(user_id)
    return result


@tool
def list_all_tasks() -> str:
    """List all tasks across all folders with their completion status."""
    user_id = get_user_id_from_context()
    
    tasks = firebase_client._get_user_tasks_ref(user_id).stream()
    task_list = []
    
    for task in tasks:
        task_data = task.to_dict()
        status = "✓" if task_data.get('completed') else "○"
        folder = task_data.get('folder', 'unknown')
        task_list.append(f"{status} {task_data['name']} ({folder})")
    
    if not task_list:
        return "No tasks found"
    
    return "\n".join(task_list)


@tool
def count_completed_tasks() -> str:
    """Count how many tasks have been completed."""
    user_id = get_user_id_from_context()
    
    tasks = firebase_client._get_user_tasks_ref(user_id).stream()
    total = 0
    completed = 0
    
    for task in tasks:
        total += 1
        if task.to_dict().get('completed', False):
            completed += 1
    
    if total == 0:
        return "You don't have any tasks yet"
    
    return f"You have completed {completed} out of {total} tasks ({round(completed/total*100, 1)}% completion rate)"


@tool 
def search_tasks(query: str) -> str: 
    """Search for tasks by partial name match.

    Use this when the user gives a partial or unclear task name.

    Args: 
        query: Partial task name to search for (e.g, "workout", "call", "run")

    Returns: 
          List of matching tasks with their exact names    
    """
    user_id = get_user_id_from_context()
    query = query.lower().strip()

    print(f"🔍 Searching tasks for: '{query}'")
    
    all_tasks = firebase_client._get_user_tasks_ref(user_id).stream()
    matches = []
    
    for task in all_tasks:
        task_data = task.to_dict()
        task_name = task_data.get('name', '')
        
        if query.lower() in task_name.lower():
            status = "✓" if task_data.get('completed') else "○"
            matches.append(f"{status} {task_name}")
    
    if not matches:
        return f"No tasks found matching '{query}'"
    
    return f"Found {len(matches)} task(s) matching '{query}':\n" + "\n".join(matches)


@tool
def mark_task_as_priority(task_name: str, reason: str = "") -> str:
    """
    Mark a task as high priority based on user intent or behavior.
    Use this when:
    - User explicitly says "this is important/urgent"
    - User asks about a task repeatedly
    - Context suggests importance (deadline, consequences mentioned)
    
    Args:
        task_name: Name of the task
        reason: Why you think it's priority (for learning)
    
    Returns:
        Confirmation message
    """
    user_id = get_user_id_from_context()
    
    tasks = firebase_client._get_user_tasks_ref(user_id).stream()
    
    for task in tasks:
        task_data = task.to_dict()
        if task_data['name'].lower() == task_name.lower():
            task_ref = firebase_client._get_user_tasks_ref(user_id).document(task.id)
            
            # Update priority
            task_ref.update({
                'is_high_priority': True,
                'priority_score': 1.0,
                'priority_reason': reason,
                'priority_marked_at': datetime.now(pytz.UTC).isoformat()
            })
            
            return f"Marked '{task_name}' as high priority. Reason: {reason}"
    
    return f"Task '{task_name}' not found."