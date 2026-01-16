# backend/tools/cleanup_actions.py

from langchain_core.tools import tool
from utils.firebase_client import FirebaseClient
from datetime import datetime, timezone
import inspect

firebase_client = FirebaseClient()

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


@tool
def handle_cleanup_action(action: str, task_name: str, insight_id: str = None) -> str:
    """
    Handle user's decision on a cleanup insight for a stale task.
    
    Args:
        action: User's choice - "delete", "keep", or "complete"
        task_name: Name of the task (natural language)
        insight_id: Optional insight ID to mark as resolved
    
    Returns:
        Confirmation message
    
    Examples:
        handle_cleanup_action("delete", "internship application")
        handle_cleanup_action("complete", "submit report")
        handle_cleanup_action("keep", "side project")
    """
    from utils.intent_resolver import intent_resolver
    
    user_id = get_user_id_from_context()
    action = action.lower().strip()
    
    # Resolve task name
    match = intent_resolver.resolve_task_name(task_name, only_incomplete=False, user_id=user_id)
    if not match:
        return f"❌ Couldn't find task matching '{task_name}'"
    
    task_exact_name = match['exact_name']
    
    # Execute action
    if action in ['delete', 'remove']:
        result = firebase_client.delete_task(task_exact_name, user_id)
        action_msg = f"🗑️ Deleted '{task_exact_name}'"
    
    elif action in ['complete', 'done', 'finish']:
        result = firebase_client.mark_task_complete(task_exact_name, user_id)
        action_msg = f"✅ Marked '{task_exact_name}' as complete"
    
    elif action in ['keep', 'save', 'ignore', 'leave']:
        # Don't delete, just dismiss the insight
        action_msg = f"👍 Keeping '{task_exact_name}' - I won't ask again"
    
    else:
        return f"❌ Unknown action '{action}'. Please say 'delete', 'complete', or 'keep'"
    
    # Mark insight as resolved if insight_id provided
    if insight_id:
        try:
            firebase_client.db.collection('monitor_insights').document(insight_id).update({
                'resolved': True,
                'resolved_at': datetime.now(timezone.utc),
                'resolution_action': action
            })
        except:
            pass  # Insight might not exist, that's okay
    
    return action_msg


@tool
def list_pending_cleanup_actions() -> str:
    """
    List all tasks that need user decision from cleanup insights.
    
    Returns:
        List of tasks awaiting user action
    """
    user_id = get_user_id_from_context()
    db = firebase_client.db
    
    # Get unresolved cleanup insights
    insights_ref = db.collection('monitor_insights')
    query = insights_ref.where('user_id', '==', user_id) \
                        .where('type', '==', 'high_priority_stale_warning') \
                        .where('resolved', '==', False)
    
    pending = []
    for doc in query.stream():
        insight_data = doc.to_dict()
        pending.append({
            'task_name': insight_data['data']['task_name'],
            'reason': insight_data['data']['reason'],
            'insight_id': doc.id
        })
    
    if not pending:
        return "✅ No pending cleanup actions"
    
    result = f"You have {len(pending)} task(s) awaiting your decision:\n"
    for item in pending:
        result += f"  • {item['task_name']} ({item['reason']})\n"
    
    return result