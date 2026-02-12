# voicelog_graph.py
import os
from typing import TypedDict, Literal, Annotated
from operator import add
import uuid
import sqlite3
import re
import json
from datetime import datetime, timedelta

from dotenv import load_dotenv
from utils.timing import LatencyTracker
from langchain_openai import ChatOpenAI

# LangSmith imports
from langsmith import traceable

# Import ReAct debugger (optional - set REACT_DEBUG=true in env to enable)
from agents.react_debugger import create_debug_callback

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.postgres import PostgresStore

# Your tools
from tools.crud_tools import (
    create_folder, create_task, delete_task, delete_folder,
    mark_task_complete, mark_task_incomplete, move_task,
    edit_task, edit_folder_name, get_folder_contents,
    list_all_folders, list_all_tasks, count_completed_tasks,
    search_tasks, mark_task_as_priority,
)

from tools.date_tools import (
    get_current_date, 
    get_date_in_days, 
    get_next_weekday, 
    parse_relative_date, 
    calculate_days_between 
)

from tools.cleanup_actions import handle_cleanup_action, list_pending_cleanup_actions

from tools.analysis_tools import (
    get_productivity_patterns,
    get_procrastination_report,
    get_weekly_accountability_summary,
    get_folder_focus_summary,
    get_tasks_by_filter,
)

load_dotenv()

# Enable LangSmith tracing
os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGCHAIN_TRACING_V2", "true")
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "voicelog-production")

print("=" * 50)
print("🔍 LANGSMITH CONFIGURATION:")
print(f"   Tracing: {os.getenv('LANGCHAIN_TRACING_V2')}")
print(f"   Project: {os.getenv('LANGCHAIN_PROJECT')}")
print(f"   API Key: {os.getenv('LANGCHAIN_API_KEY', 'NOT SET')[:20]}...")
print("=" * 50)

# Debug mode for ReAct tracing
REACT_DEBUG = os.getenv("REACT_DEBUG", "false").lower() == "true"

# ── Tiered LLM Setup ──
# Mini: cheap classification (router, memory extraction) ~$0.0002/call
# Main: tool-calling agents (CRUD, analysis)             ~$0.005/call
_api_key = os.getenv("OPENAI_API_KEY")

llm_mini = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    api_key=_api_key,
    max_tokens=100,   # Router/memory only need short outputs
)

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    api_key=_api_key,
    max_tokens=700,   # Enough room for ReAct tool chains (date tool → action tool)
)

# Mistral 3B via Ollama – local fallback for memory extraction
memory_llm = ChatOpenAI(
    model="mistral:3b-instruct",
    temperature=0,
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

print(f"🧠 LLM Tier: Router/Memory → gpt-4o-mini | Agents → gpt-4o")

# ========================================
# STATE DEFINITION
# ========================================

class VoiceLogState(TypedDict, total=False):
    messages: Annotated[list[dict], add]
    user_command: str
    route_decision: Literal["crud", "analysis"]
    final_response: str
    new_memories: list[dict]
    user_timezone: str

# ========================================
# GLOBAL CONNECTIONS
# ========================================

# Environment-based database configuration
# Set USE_SQLITE=false in production to use PostgreSQL
USE_SQLITE = os.getenv("USE_SQLITE", "true").lower() == "true"

if USE_SQLITE:
    # SQLite store for local development
    from langgraph.store.memory import InMemoryStore
    print("🔧 Initializing SQLite store (local development mode)...")
    _memory_store = InMemoryStore()
    print("✅ SQLite store initialized")
else:
    # PostgreSQL store for production
    DB_URI = os.getenv(
        "POSTGRES_URL",
        os.getenv(
            "DATABASE_URL",
            "postgresql://voicelog_user:voicelog_password_123@localhost:5432/voicelog_memory",
        )
    )

    print("🔧 Initializing PostgreSQL store (production mode)...")
    _store_context_manager = PostgresStore.from_conn_string(DB_URI)
    _memory_store = _store_context_manager.__enter__()

    try:
        _memory_store.setup()
        print("✅ PostgreSQL store initialized")
    except Exception as e:
        print(f"⚠️  Store setup warning: {e}")

# ========================================
# HELPER FUNCTIONS
# ========================================

def clean_response(text: str) -> str:
    """Remove verbose fluff from LLM responses to keep them concise"""
    # Remove common filler phrases
    fluff_phrases = [
        "Keep up the good work!",
        "Keep up the good work.",
        "Is there anything else you'd like to know?",
        "Is there anything else I can help you with?",
        "Feel free to ask if you need anything else",
        "which is excellent!",
        "Great job!",
        "Excellent!",
        "Let me know if you need anything else",
        "Hope this helps!",
    ]

    for phrase in fluff_phrases:
        text = text.replace(phrase, "")

    # Clean up extra spaces, periods, and trailing punctuation
    text = text.replace("  ", " ").replace("..", ".").replace(". .", ".").strip()

    # Remove trailing spaces before punctuation
    text = text.replace(" .", ".").replace(" !", "!").replace(" ?", "?")

    return text

# ========================================
# NODES
# ========================================

@traceable(
    name="memory_extraction",
    run_type="llm",
    tags=["memory", "preferences"]
)
def extract_memory_node(state: VoiceLogState, config):
    """Extract long-term preferences into Postgres-backed store."""
    from langgraph.config import get_store

    tracker = LatencyTracker()
    tracker.start("Memory Extraction")

    try:
        store = get_store()
        print("✅ Store accessed via get_store()")
    except Exception as e:
        print(f"⚠️  get_store() failed: {e}")
        tracker.end("Memory Extraction")
        return {"new_memories": []}

    user_command = state.get("user_command") or ""
    if not user_command.strip():
        tracker.end("Memory Extraction")
        return {"new_memories": []}

    print(f"🔍 Extracting memory from: '{user_command}'")

    user_id = config["configurable"]["user_id"]
    namespace = (user_id, "preferences")

    prior_prefs = store.search(namespace, query=user_command, limit=3)
    prior_text = "\n".join([str(item.value) for item in prior_prefs]) if prior_prefs else ""

    prompt = f"""
You are a memory extraction agent for VoiceLog AI. Extract ONLY long-term user preferences, habits, and personal facts that should be remembered across conversations.

Previously stored preferences:
{prior_text}

Current user message:
"{user_command}"

EXTRACT these (look for "always", "all", "should", "prefer"):
- Personal facts: job, city, role, stuff that they like.
- Habits & routines: repeated behaviors, schedules.
- Organizational preferences: "AI tasks go in Problems folder", "work tasks are high priority"
- Folder routing rules: "all X tasks should be in Y folder"
- Work patterns: when/how they usually work.
- Timezone/location context.
- Task categorization preferences: which tasks belong in which folders

DO NOT EXTRACT:
- One-time commands: "create task X", "delete task Y", "move THIS task"
- Pure analysis/insight requests: "how am I doing?", "what did I finish?"
- Status updates: "I'm done with X", "I finished Y"
- One-time activities: "I opened X", "I did Y today"
- Temporary scheduling: "remind me today", "schedule this tomorrow"
- Questions about current state: "what tasks do I have?"

KEY DISTINCTION:
✅ EXTRACT: "All my AI tasks should go in Problems folder" (rule for FUTURE tasks)
❌ DON'T: "Move this AI task to Problems folder" (one-time action on THIS task)

Return a JSON array with 0–3 items. Each item:
- "pref": short natural-language statement of the preference/fact.
- "confidence": "high" | "medium" | "low".
- "source": short reason, e.g. "explicit statement" or "inferred pattern".

If no long-term preferences are present, return [].

Example:
[
  {{"pref": "User prefers morning workouts", "confidence": "high", "source": "explicit statement"}},
  {{"pref": "User organizes AI tasks in Problems folder", "confidence": "medium", "source": "inferred pattern"}}
]

CRITICAL:
- Do NOT include any explanation.
- Do NOT use Markdown or code fences.
- Your ENTIRE response must be ONLY the JSON array.
"""

    try:
        resp = llm_mini.invoke(prompt)
        raw = resp.content.strip()
        print(f"🤖 LLM (mini) response: {raw[:200]}...")

        # 1) Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 3:
                raw = parts[2].strip()

        # 2) Extract the first JSON array in the text
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            raw_json = match.group(0).strip()
        else:
            raw_json = raw  # fallback

        # 3) Parse JSON
        try:
            memories = json.loads(raw_json)
        except json.JSONDecodeError as je:
            print(f"❌ JSON parse failed: {je} | raw_json: {raw_json}")
            memories = []

        # 4) Store only dict items
        if isinstance(memories, list):
            cleaned_memories = []
            for mem in memories:
                if isinstance(mem, dict):
                    store.put(namespace, f"pref_{uuid.uuid4().hex[:8]}", mem)
                    print(f"💾 Stored: {mem}")
                    cleaned_memories.append(mem)
            memories = cleaned_memories
        else:
            memories = []

    except Exception as e:
        print(f"❌ Memory extraction failed: {e}")
        memories = []

    if memories:
        print(f"🧠 Saved {len(memories)} preferences")

    tracker.end("Memory Extraction")
    return {"new_memories": memories}

@traceable(
    name="router_decision",
    run_type="chain",
    tags=["routing", "classification"]
)
def router_node(state: VoiceLogState, config):
    """Classify user command as CRUD or ANALYSIS."""
    from langgraph.config import get_store

    tracker = LatencyTracker()
    tracker.start("Router")

    try:
        store = get_store()
    except Exception:
        store = None

    command = state.get("user_command", "") or ""
    user_id = config["configurable"]["user_id"]
    namespace = (user_id, "preferences")

    pref_text = ""
    prefs = []
    if store:
        prefs = store.search(namespace, query=command or "task", limit=5)
        pref_text = "\n".join(
            [p.value.get("pref", "") for p in prefs if isinstance(p.value, dict)]
        )

    if not command:
        tracker.end("Router")
        return {"route_decision": "crud"}

    classification_prompt = f"""You are an orchestrator agent for VoiceLog AI. Route user messages to the correct specialized agent based on their INTENT, not exact words.

User long-term preferences (if any):
{pref_text}

=== TWO AGENTS ===

CRUD Agent - Takes action on tasks/folders
ANALYSIS Agent - Provides insights about productivity and task history

=== ROUTING RULE ===

Ask yourself: "What does the user WANT?"

→ CRUD if user wants to:
  • DO something (create, delete, update, move, rename)
  • SEE what they currently have (list, show current tasks/folders)
  • CHANGE task status (complete, incomplete, prioritize)
  
→ ANALYSIS if user wants to:
  • UNDERSTAND patterns (when/how they work)
  • GET insights (productivity, procrastination, progress)
  • REVIEW history (what they accomplished, completion stats)
  • ASK questions about their behavior/performance

=== NATURAL LANGUAGE EXAMPLES ===

CRUD (Action/Current State):
- "I'm done with my workout" → CRUD (mark complete)
- "Add buy groceries to my list" → CRUD (create task)
- "What do I need to do today?" → CRUD (show current tasks)
- "Remove that old task" → CRUD (delete)
- "Put this in my work folder" → CRUD (move)
- "I need to finish the report by Friday" → CRUD (create with deadline)

ANALYSIS (Insights/History):
- "How's my week going?" → ANALYSIS (progress review)
- "Did I get anything done today?" → ANALYSIS (completion history)
- "Am I behind on stuff?" → ANALYSIS (procrastination check)
- "What time do I usually finish tasks?" → ANALYSIS (pattern)
- "Show me what I accomplished" → ANALYSIS (achievement review)
- "Which things did I complete?" → ANALYSIS (historical accomplishments)

=== KEY DISTINCTION ===

Present/Future focused = CRUD
- "What tasks DO I have?" (current)
- "What should I work on?" (current)
- "I need to..." (create new)

Past focused / Pattern seeking = ANALYSIS  
- "What tasks DID I finish?" (history)
- "When DO I usually work?" (pattern)
- "How AM I doing?" (performance)

=== YOUR TASK ===

User message: "{command}"

What is their intent?
- Taking action or viewing current state? → CRUD
- Seeking insights or reviewing history? → ANALYSIS

Reply with ONLY one word: CRUD or ANALYSIS

CRITICAL: Your ENTIRE response must be ONLY the word "CRUD" or "ANALYSIS". No explanations, no extra text, no newlines.
"""

    response = llm_mini.invoke(classification_prompt)
    raw_decision = response.content.strip().lower()

    # Extract only the first line and first word (handle cases where LLM adds extra text)
    try:
        first_line = raw_decision.split('\n')[0].strip()
        decision = first_line.split()[0] if first_line else 'crud'
    except (IndexError, AttributeError):
        print(f"⚠️  ROUTER ERROR: Could not parse '{raw_decision}', defaulting to CRUD")
        decision = 'crud'

    # Validate decision is either 'crud' or 'analysis'
    if decision not in ['crud', 'analysis']:
        print(f"⚠️  ROUTER WARNING: Invalid decision '{raw_decision}', defaulting to CRUD")
        decision = 'crud'

    print(f"🔀 ROUTER: '{command}' → {decision.upper()}  (prefs used: {len(prefs)})")

    tracker.end("Router")
    return {"route_decision": decision}

@traceable(
    name="crud_execution",
    run_type="chain",
    tags=["crud", "task-management"]
)
def crud_node(state: VoiceLogState, config):
    """Handle CRUD operations with full conversation context."""
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage, AIMessage
    from langgraph.config import get_store

    tracker = LatencyTracker()
    tracker.start("CRUD")

    try:
        store = get_store()
    except Exception:
        store = None

    command = state.get("user_command", "") or ""
    messages = state.get("messages", []) or []

    print(f"\n🔧 CRUD Node:")
    print(f"   Command: '{command}'")
    print(f"   History: {len(messages)} messages")

    if not command.strip():
        tracker.end("CRUD")
        return {"final_response": "Error: No command received"}

    tools_list = [
        create_folder, create_task, delete_task, delete_folder,
        mark_task_complete, mark_task_incomplete, move_task,
        edit_task, edit_folder_name, get_folder_contents,
        list_all_folders, list_all_tasks, count_completed_tasks,
        search_tasks, mark_task_as_priority,
        get_current_date, get_date_in_days, get_next_weekday,
        parse_relative_date, calculate_days_between, 
        handle_cleanup_action, list_pending_cleanup_actions
    ]

    user_id = config["configurable"]["user_id"]
    namespace = (user_id, "preferences")

    prefs_text = ""
    if store:
        prefs = store.search(namespace, query="task reminder productivity", limit=5)
        prefs_text = "\n".join(
            [p.value.get("pref", "") for p in prefs if isinstance(p.value, dict)]
        )

    # Build chat history
    chat_history = []
    for msg in messages[-10:]:
        if msg.get("role") == "human":
            chat_history.append(HumanMessage(content=msg.get("content", "")))
        elif msg.get("role") == "ai":
            chat_history.append(AIMessage(content=msg.get("content", "")))

    recent_context = ""
    if len(messages) >= 2:
        prev_msg = messages[-2]
        if prev_msg.get("role") == "human":
            recent_context = f"\n\nMOST RECENT USER MESSAGE:\n'{prev_msg.get('content', '')}'\n"

    user_timezone = state.get("user_timezone")        

    system_prompt = f"""You are a task management assistant responsible for creating, updating, organizing, and completing user tasks using the available tools.

Your goal is to correctly interpret user intent, and  resolve task references using context. 

=== USER CONTEXT ===
User timezone: {user_timezone}

{prefs_text}
{recent_context}

Use preferences only to suggest times, folders, and task organization strategies. Preferences must never override explicit user instructions.

Context resolution rules:
- If the user refers to a task using vague terms like "it", "this", or "that", identify the task using recent conversation context or recent notifications.
- If multiple tasks match the reference, do not guess. Ask for clarification.
- If no task matches, state that clearly.

=== EXECUTION FLOW ===
For every user request, follow this order:
1. Identify what the user is referring to — call search_tasks or list_all_tasks FIRST to check if a matching task already exists.
2. If the task exists: UPDATE it (edit_task, mark_task_complete, move_task, etc.) — do NOT create a duplicate.
3. If the task does NOT exist: only then create_task.
4. Resolve any dates using date_tools if required.
5. Detect urgency and mark priority if applicable.
6. Return a brief confirmation or result.

CRITICAL: When the user says "I need to do X" or "X by tomorrow", ALWAYS search first. The user may be setting a deadline on an existing task, not creating a new one.

=== DATE HANDLING (STRICT) ===
You must never calculate dates mentally.

Always use date tools:
- "today" → get_current_date()
- "tomorrow" → get_date_in_days(1)
- "in N days" → get_date_in_days(N)
- "next Monday" → get_next_weekday("Monday")
- "on the 25th" → parse_relative_date("on the 25th")

When creating or editing tasks with due dates:
1. Call the appropriate date tool.
2. Use the returned value as due_date in "YYYY-MM-DD" format.
3. Only set a due date if the user explicitly provides one.
4. Never generate or assume a due date.

=== PRIORITY DETECTION ===
Detect urgency from language cues such as:
- "must", "need to", "have to", "urgent", "asap", "critical"
- Explicit deadlines like "by Friday" or "before 5pm"

When urgency is detected, call mark_task_as_priority(task_name, reason).

=== TOOL USAGE RULES ===
- Use tools only when their criteria are met.
- If a tool fails, explain the failure and suggest the next step.
- SEQUENTIAL EXECUTION: When a request involves multiple dependent actions, execute them ONE AT A TIME. Wait for each step to succeed before starting the next. NEVER run dependent actions in parallel.
  Examples:
  - "Move task to Fitness and delete Personal folder" → Step 1: move_task, confirm success. Step 2: delete_folder.
  - "Create a folder and add a task to it" → Step 1: create_folder, confirm success. Step 2: create_task.
  - "Rename the task and mark it complete" → Step 1: edit_task, confirm success. Step 2: mark_task_complete.
- FOLDER DELETION: Before deleting a folder, check if it has tasks (use get_folder_contents). If it does, ASK the user: "This folder has X task(s). Should I move them to another folder or delete them along with the folder?" Wait for the user's answer before proceeding.

=== AVAILABLE TOOLS ===
Cleanup Actions:
- handle_cleanup_action, list_pending_cleanup_actions

Date Tools:
- get_current_date, get_date_in_days, get_next_weekday
- parse_relative_date, calculate_days_between

Task Management:
- create_task, delete_task, edit_task
- mark_task_complete, mark_task_incomplete
- move_task, mark_task_as_priority, search_tasks

Organization:
- create_folder, delete_folder, edit_folder_name
- list_all_folders, list_all_tasks, get_folder_contents

=== RESPONSE STYLE === (STRICT) ===
- MAXIMUM 2 sentences. Be extremely brief.
- NO pleasantries like "Done!" or "Is there anything else?"
- Just confirm the action or state the result.
- NO markdown, bullet points, or questions.
"""

    print("   Creating react agent...")

    try:
        agent_graph = create_react_agent(llm, tools_list, prompt=system_prompt)

        all_messages = chat_history + [HumanMessage(content=command)]

        # Prepare config with LangSmith metadata
        invoke_config = {
            "messages": all_messages,
            "metadata": {
                "user_id": user_id,
                "command": command[:100],
                "agent_type": "crud",
                "has_preferences": bool(prefs_text),
                "message_count": len(messages)
            },
            "tags": ["crud", f"user:{user_id}", "voicelog"]
        }

        # Add callback for real-time ReAct tracing if debug mode enabled
        if REACT_DEBUG:
            invoke_config["callbacks"] = [create_debug_callback(verbose=True)]
            print("🔍 ReAct Debug Mode: ENABLED (CRUD)")

        result = agent_graph.invoke(invoke_config)

        # 🔍 DEBUG: Print ReAct reasoning steps
        print("\n" + "="*80)
        print("🧠 REACT AGENT REASONING TRACE (CRUD)")
        print("="*80)

        for i, msg in enumerate(result.get("messages", []), 1):
            msg_type = msg.__class__.__name__

            if msg_type == "HumanMessage":
                print(f"\n[{i}] 👤 USER:")
                print(f"    {msg.content[:200]}")

            elif msg_type == "AIMessage":
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    print(f"\n[{i}] 🤖 AGENT THOUGHT → ACTION:")
                    for tool_call in msg.tool_calls:
                        print(f"    📌 Calling: {tool_call['name']}")
                        print(f"    📋 Args: {tool_call['args']}")
                else:
                    print(f"\n[{i}] 🤖 AGENT FINAL RESPONSE:")
                    print(f"    {msg.content}")

            elif msg_type == "ToolMessage":
                print(f"\n[{i}] 🔧 TOOL RESULT (Observation):")
                content_preview = str(msg.content)[:300]
                print(f"    {content_preview}{'...' if len(str(msg.content)) > 300 else ''}")

        print("\n" + "="*80 + "\n")

        response = result["messages"][-1].content if result.get("messages") else "No response"

        # Clean up verbose phrases
        response = clean_response(response)

        print(f"✅ CRUD: {response}\n")

        tracker.end("CRUD")

        return {
            "messages": [
                {"role": "human", "content": command},
                {"role": "ai", "content": response},
            ],
            "final_response": response,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"Sorry, error: {str(e)}"

        tracker.end("CRUD")

        return {
            "messages": [
                {"role": "human", "content": command},
                {"role": "ai", "content": error_msg},
            ],
            "final_response": error_msg,
        }

@traceable(
    name="analysis_execution",
    run_type="chain",
    tags=["analysis", "productivity"]
)    
def analysis_node(state: VoiceLogState, config):
    """Handle productivity analysis with coordination awareness."""
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage, AIMessage
    from langgraph.config import get_store

    tracker = LatencyTracker()
    tracker.start("Analysis")

    try:
        store = get_store()
    except Exception:
        store = None

    command = state.get("user_command", "") or ""
    messages = state.get("messages", []) or []
    user_timezone = state.get("user_timezone")

    if not user_timezone:
        tracker.end("Analysis")
        return {
            "final_response": "I need your timezone to analyze your productivity accurately."
        }

    print(f"\n📊 ANALYSIS Node:")
    print(f"   Command: '{command}'")
    print(f"   History: {len(messages)} messages")

    tools_list = [
        get_productivity_patterns,
        get_procrastination_report,
        get_weekly_accountability_summary,
        get_folder_focus_summary,
        get_tasks_by_filter,
        get_current_date,
        get_date_in_days,
        get_next_weekday,
        parse_relative_date,
        calculate_days_between
    ]

    user_id = config["configurable"]["user_id"]
    namespace = (user_id, "preferences")

    prefs_text = ""
    if store:
        prefs = store.search(namespace, query="productivity", limit=5)
        prefs_text = "\n".join(
            [p.value.get("pref", "") for p in prefs if isinstance(p.value, dict)]
        )

    # Build chat history
    chat_history = []
    for msg in messages[-10:]:
        if msg.get("role") == "human":
            chat_history.append(HumanMessage(content=msg.get("content", "")))
        elif msg.get("role") == "ai":
            chat_history.append(AIMessage(content=msg.get("content", "")))

    system_prompt = f"""You are a supportive productivity coach integrated into VoiceTask.

USER PREFERENCES (long-term memory):
{prefs_text}

-----CRITICAL - DATE HANDLING----: 
You are Terrible at calculating dates. You MUST use the date tools for ANY date-related questions: 

- User asks "what's today?" -> call get_current_date()
- User asks "What's next Monday?" -> call get_next_weekday("Monday")
- User says "5 days ago" -> call get_date_in_days(-5)

NEVER guess dates. ALWAYS use tools. 

-----TIME RULES (CRITICAL)-----:
- All timestamps are stored in UTC.
- You MUST convert UTC -> user_timezone before reasoning.
- NEVER assume a timezone.
- When reporting completion times, include both date and time in user's local timezone.
- Format: "January 15 at 1:16 AM" (natural, human-readable format). 

-----TOOL RULES (CRITICAL)-----:
- If the question depends on task history or patterns,
  you MUST call the appropriate tool before responding.
- Tools return structured facts, not sentences.
- If you respond without calling a tool for a data-dependent question, your response is incorrect. 

-----INTENT -> TOOL MAPPING-----:
- Productivity, patterns, "how am I doing" → get_productivity_patterns
- Avoidance, procrastination → get_procrastination_report
- Weekly summaries → get_weekly_accountability_summary
- Focus, categories → get_folder_focus_summary
- Task filtering, "when did I complete", "what did I finish", "when was the due", "what's due soon"? → get_tasks_by_filter
  Supports: completed, is_high_priority, hour, due_before (YYYY-MM-DD), due_after (YYYY-MM-DD), overdue_only (bool).
  Use due_before/due_after for "due this week" queries. Use overdue_only=True for "am I behind?" questions.

-----RESPONSE STYLE-----:
- MAXIMUM 2 sentences. Be extremely concise.
- NO pleasantries like "Keep up the good work!" or "Is there anything else?"
- Just state the key facts and insights directly.
- NO markdown, bullet points, headers, or questions.
- Sound natural but brief.

User timezone: {user_timezone}
"""

    print("   Creating react agent...")

    try:
        agent_graph = create_react_agent(llm, tools_list, prompt=system_prompt)

        all_messages = chat_history + [HumanMessage(content=command)]

        # Prepare config with LangSmith metadata
        invoke_config = {
            "messages": all_messages,
            "metadata": {
                "user_id": user_id,
                "command": command[:100],
                "agent_type": "analysis",
                "timezone": user_timezone,
                "message_count": len(messages)
            },
            "tags": ["analysis", f"user:{user_id}", "voicelog"]
        }

        # Add callback for real-time ReAct tracing if debug mode enabled
        if REACT_DEBUG:
            invoke_config["callbacks"] = [create_debug_callback(verbose=True)]
            print("🔍 ReAct Debug Mode: ENABLED (ANALYSIS)")

        result = agent_graph.invoke(invoke_config)

        # 🔍 DEBUG: Print ReAct reasoning steps
        print("\n" + "="*80)
        print("🧠 REACT AGENT REASONING TRACE (ANALYSIS)")
        print("="*80)

        for i, msg in enumerate(result.get("messages", []), 1):
            msg_type = msg.__class__.__name__

            if msg_type == "HumanMessage":
                print(f"\n[{i}] 👤 USER:")
                print(f"    {msg.content[:200]}")

            elif msg_type == "AIMessage":
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    print(f"\n[{i}] 🤖 AGENT THOUGHT → ACTION:")
                    for tool_call in msg.tool_calls:
                        print(f"    📌 Calling: {tool_call['name']}")
                        print(f"    📋 Args: {tool_call['args']}")
                else:
                    print(f"\n[{i}] 🤖 AGENT FINAL RESPONSE:")
                    print(f"    {msg.content}")

            elif msg_type == "ToolMessage":
                print(f"\n[{i}] 🔧 TOOL RESULT (Observation):")
                content_preview = str(msg.content)[:300]
                print(f"    {content_preview}{'...' if len(str(msg.content)) > 300 else ''}")

        print("\n" + "="*80 + "\n")

        response = result["messages"][-1].content if result.get("messages") else "No response"

        # Clean up verbose phrases
        response = clean_response(response)

        tracker.end("Analysis")

        return {
            "messages": [
                {"role": "human", "content": command},
                {"role": "ai", "content": response},
            ],
            "final_response": response,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"Analysis error: {str(e)}"

        tracker.end("Analysis")

        return {
            "messages": [
                {"role": "human", "content": command},
                {"role": "ai", "content": error_msg},
            ],
            "final_response": error_msg,
        }

# ========================================
# GRAPH BUILDER
# ========================================

def create_voicelog_graph():
    """Create and compile the LangGraph workflow."""
    workflow = StateGraph(VoiceLogState)

    workflow.add_node("extract_memory", extract_memory_node)
    workflow.add_node("router", router_node)
    workflow.add_node("crud", crud_node)
    workflow.add_node("analysis", analysis_node)

    workflow.set_entry_point("extract_memory")
    workflow.add_edge("extract_memory", "router")
    workflow.add_conditional_edges(
        "router",
        lambda state: state["route_decision"],
        {"crud": "crud", "analysis": "analysis"},
    )
    workflow.add_edge("crud", END)
    workflow.add_edge("analysis", END)

    # SQLite checkpointer
    conn = sqlite3.connect("voicelog_memory.db", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    print("💾 Checkpointer: voicelog_memory.db")

    # Memory store (SQLite or PostgreSQL based on config)
    store_type = "SQLite" if USE_SQLITE else "PostgreSQL"
    print(f"🧠 {store_type} Store: Ready")

    return workflow.compile(checkpointer=checkpointer, store=_memory_store)

voicelog_app = create_voicelog_graph()
print("✅ VoiceLog LangGraph with Agent Coordination + LangSmith Tracing!\n")