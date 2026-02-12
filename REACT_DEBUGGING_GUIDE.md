# 🔍 ReAct Agent Debugging Guide

This guide shows you how to see your ReAct agent's internal reasoning process.

---

## 🎯 What You'll See

The ReAct (Reasoning + Acting) framework follows this loop:

```
1. THOUGHT: Agent thinks about what to do
2. ACTION: Agent calls a tool
3. OBSERVATION: Agent sees the tool result
4. THOUGHT: Agent thinks about what to do next
5. Repeat steps 2-4 until ready to answer
6. FINAL RESPONSE: Agent responds to user
```

---

## 📊 Method 1: Basic Message Trace (Always On)

**What it does:** Shows you all messages exchanged in the ReAct loop

**How to use:** Already enabled! Just run your app normally.

**Example output:**
```bash
================================================================================
🧠 REACT AGENT REASONING TRACE
================================================================================

[1] 👤 USER:
    Analyze my days

[2] 🤖 AGENT THOUGHT → ACTION:
    📌 Calling: get_productivity_patterns
    📋 Args: {'user_id': 'gXLno2jNqIP0hTkV7g6zFQCutf83'}

[3] 🔧 TOOL RESULT (Observation):
    {'peak_day': 'Friday', 'peak_hour': '1 PM', 'avg_completion_time': 132.5}

[4] 🤖 AGENT THOUGHT → ACTION:
    📌 Calling: get_current_date
    📋 Args: {}

[5] 🔧 TOOL RESULT (Observation):
    2026-01-31

[6] 🤖 AGENT FINAL RESPONSE:
    You're most productive around 1 PM on Fridays. Tasks take you 132 hours on average.

================================================================================
```

---

## 🚀 Method 2: Real-Time Callback Tracing (Advanced)

**What it does:** Shows you the agent's thoughts AS THEY HAPPEN with detailed callbacks

**How to enable:**

1. Set environment variable:
   ```bash
   export REACT_DEBUG=true
   ```

2. Or add to your `.env` file:
   ```bash
   REACT_DEBUG=true
   ```

3. Restart your backend:
   ```bash
   python app.py
   ```

**Example output:**
```bash
🔍 ReAct Debug Mode: ENABLED (ANALYSIS)

============================================================
💭 STEP 1: AGENT THINKING...
============================================================
🎯 DECISION: Will call a tool

🔧 ACTION: Calling tool 'get_productivity_patterns'
📥 INPUT: {'user_id': 'gXLno2jNqIP0hTkV7g6zFQCutf83'}
📤 OUTPUT: {'peak_day': 'Friday', 'peak_hour': '1 PM'}...
👀 OBSERVATION: Agent now processing this result...

============================================================
💭 STEP 2: AGENT THINKING...
============================================================
✅ DECISION: Ready to respond to user

============================================================
🏁 AGENT FINISHED
   Return: You're most productive around 1 PM on Fridays
============================================================
```

---

## 🧪 Method 3: LangSmith (Professional Observability)

**What it does:** Web-based UI to visualize agent traces, performance, and debugging

**How to enable:**

1. Sign up at [smith.langchain.com](https://smith.langchain.com)

2. Get your API key from settings

3. Add to `.env`:
   ```bash
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=your_api_key_here
   LANGCHAIN_PROJECT=voicelog-ai
   ```

4. Restart backend

5. Visit [smith.langchain.com](https://smith.langchain.com) to see:
   - Visual tree of all agent steps
   - Latency for each step
   - Token usage
   - Error tracking
   - Comparison between runs

**Benefits:**
- Beautiful visual interface
- Search and filter traces
- Compare different runs
- Share traces with team
- Monitor production issues

---

## 🎨 Method 4: Custom Logging

**What it does:** Create your own custom logs for specific debugging needs

**How to use:** Modify `react_debugger.py` callback methods:

```python
def on_tool_start(self, serialized, input_str, **kwargs):
    """Log when tool is called"""
    tool_name = serialized.get("name")

    # Add custom logging here
    if tool_name == "get_productivity_patterns":
        print(f"⚡ PERFORMANCE CHECK: Analyzing productivity...")

    print(f"🔧 Calling: {tool_name}")
    print(f"📋 Input: {input_str}")
```

---

## 📈 Comparing Debug Levels

| Method | Detail Level | Performance Impact | Setup |
|--------|-------------|-------------------|-------|
| Basic Trace | Medium | None | ✅ Already on |
| Callback Debug | High | Minimal | Set `REACT_DEBUG=true` |
| LangSmith | Very High | Minimal | API key required |
| Custom Logging | Custom | Low-Medium | Modify callback code |

---

## 🔧 Quick Start

**To see detailed ReAct tracing right now:**

1. Add to `.env`:
   ```bash
   REACT_DEBUG=true
   ```

2. Restart backend:
   ```bash
   cd backend
   python app.py
   ```

3. Send a command from your Flutter app:
   ```
   "Analyze my days"
   ```

4. Watch your terminal for detailed traces!

---

## 💡 Tips

**Debug specific commands:**
- CRUD operations: "Create a task called test"
- Analysis: "How productive am I?"
- Multi-step reasoning: "What should I focus on today?"

**What to look for:**
- ✅ Good: Agent calls the right tools in logical order
- ⚠️  Warning: Agent calls same tool multiple times (inefficient)
- ❌ Bad: Agent never calls tools but makes up answers

**Common patterns:**
- Simple CRUD: 1 thought → 1 action → response
- Complex analysis: 1 thought → 2-3 actions → response
- Multi-turn: 1 thought → 1 action → 1 thought → 1 action → response

---

## 🐛 Troubleshooting

**Issue:** Not seeing traces
- **Fix:** Make sure `REACT_DEBUG=true` is set
- **Check:** Print `os.getenv("REACT_DEBUG")` to verify

**Issue:** Too verbose, can't read logs
- **Fix:** Set `REACT_DEBUG=false` to disable callback tracing
- **Use:** Basic trace is always available (less verbose)

**Issue:** Want to trace only specific operations
- **Fix:** Modify callback to check command content before logging

---

## 🚀 Next Steps

1. Try enabling `REACT_DEBUG=true`
2. Send different commands and observe patterns
3. Identify inefficient tool usage
4. Optimize your prompts based on what you see
5. Consider LangSmith for production monitoring

Happy debugging! 🎉
