# voicelog_graph.py
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from typing import TypedDict, Literal, Annotated
from operator import add
import os
import uuid
import sqlite3
import re
import json
from datetime import datetime, timedelta

from dotenv import load_dotenv
from utils.timing import LatencyTracker
from langchain_openai import ChatOpenAI

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

# OpenAI – used for router, CRUD, analysis
llm = ChatOpenAI(
    model="gpt-4",
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY"),
)

# Mistral 7B via Ollama – used ONLY for memory extraction
memory_llm = ChatOpenAI(
    model="mistral:3b-instruct",
    temperature=0,
    base_url="http://localhost:11434/v1",
    api_key="ollama",
) 

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

DB_URI = os.getenv(
    "POSTGRES_URL",
    os.getenv(
    "DATABASE_URL",     
    "postgresql://voicelog_user:voicelog_password_123@localhost:5432/voicelog_memory",
)
)

print("🔧 Initializing PostgreSQL store...")
_store_context_manager = PostgresStore.from_conn_string(DB_URI)
_postgres_store = _store_context_manager.__enter__()

try:
    _postgres_store.setup()
    print("✅ PostgreSQL store initialized")
except Exception as e:
    print(f"⚠️  Store setup warning: {e}")

# ========================================
# NODES
# ========================================

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

EXTRACT these:
- Personal facts: job, city, role, stuff that they like.
- Habits & routines: repeated behaviors, schedules.
- Preferences: ways they like to organize or work.
- Work patterns: when/how they usually work.
- Timezone/location context.

DO NOT EXTRACT:
- One-time commands (create/delete/edit/move tasks, reminders).
- Pure analysis/insight requests.
- Anything which is related to about taking action.
- Status updates about what they JUST completed ("I'm done with X", "I finished Y").
- One-time activities ("I opened X", "I did Y today").
- Temporary scheduling ("remind me today", "schedule this tomorrow").
- Questions about current state.


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
        resp = llm.invoke(prompt)
        raw = resp.content.strip()
        print(f"🤖 LLM response: {raw[:200]}...")

        # 1) Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            # e.g. ["", "json", "[ ... ]", "This array includes..."]
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

Reply with ONLY: CRUD or ANALYSIS
"""
    
    response = llm.invoke(classification_prompt)
    decision = response.content.strip().lower()

    print(f"🔀 ROUTER: '{command}' → {decision.upper()}  (prefs used: {len(prefs)})")

    tracker.end("Router")


    return {"route_decision": decision}

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

         get_current_date,
         get_date_in_days,
         get_next_weekday,
         parse_relative_date,
         calculate_days_between, 

         handle_cleanup_action, 
         list_pending_cleanup_actions
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

    system_prompt = f"""You are a helpful task management assistant for VoiceLog AI.

=== USER CONTEXT ===

{prefs_text}
{recent_context}

Use these preferences to suggest times, folders, and strategies that match the user's habits.

=== CLEANUP ACTIONS ===

When users respond to cleanup notifications:
- "Delete it" / "Remove it" → handle_cleanup_action("delete", task_name)
- "Complete it" / "Mark it done" → handle_cleanup_action("complete", task_name)
- "Keep it" / "Leave it" → handle_cleanup_action("keep", task_name)

Context clues:
- If user says "delete/complete/keep it" without naming a task, check recent conversation
- Look for the most recent cleanup notification
- Use conversation history to identify which task they're referring to

=== DATE HANDLING ===

You cannot calculate dates mentally. ALWAYS use date tools:
- "what's today?" → get_current_date()
- "next Monday" → get_next_weekday("Monday")
- "in 5 days" → get_date_in_days(5)
- "tomorrow" → get_date_in_days(1)
- "on the 25th" → parse_relative_date("on the 25th")

When creating tasks with dates:
1. Call date tool to calculate the date
2. Call create_task(..., due_date="YYYY-MM-DD")

=== PRIORITY DETECTION ===

Detect urgency in user language:
- Strong signals: "must", "need to", "have to", "urgent", "asap", "critical"
- Deadlines: "by Friday", "before 5pm", "until tomorrow"
- When detected → call mark_task_as_priority(task_name, reason)

=== CONTEXT AWARENESS ===

When users say vague things like "it", "that", "this task":
1. Check the most recent user message
2. Look at conversation history
3. Check recent notifications

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
"""

    print("   Creating react agent...")

    try:
        agent_graph = create_react_agent(llm, tools_list, prompt=system_prompt)

        all_messages = chat_history + [HumanMessage(content=command)]

        result = agent_graph.invoke({
            "messages": all_messages
        })

        response = result["messages"][-1].content if result.get("messages") else "No response"
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

    system_prompt = f"""You are a supportive productivity coach integrated into VoiceLog.

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
- Task filtering (new) -> get_tasks_by_filter 

-----RESPONSE STYLE-----:
- Respond in 2–3 natural sentences.
- Do NOT repeat tool structure.
- No markdown language and no preamble. 
- Do NOT use bullet points or headers.
- Sound like a thoughtful human coach.

User timezone: {user_timezone}
"""

    print("   Creating react agent...")

    try:
        agent_graph = create_react_agent(llm, tools_list, prompt=system_prompt)

        all_messages = chat_history + [HumanMessage(content=command)]

        result = agent_graph.invoke({
            "messages": all_messages
        })

        response = result["messages"][-1].content if result.get("messages") else "No response"

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

    # PostgreSQL store
    print("🧠 PostgresStore: Ready")

    return workflow.compile(checkpointer=checkpointer, store=_postgres_store)

voicelog_app = create_voicelog_graph()
print("✅ VoiceLog LangGraph with Agent Coordination!\n")