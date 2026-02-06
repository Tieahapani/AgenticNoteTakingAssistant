# VoiceTask AI

An intelligent multi-agent task management assistant that converts voice input into organized, actionable tasks with advanced analytics and productivity insights.

## Overview

VoiceTask AI captures voice recordings, transcribes them on-device using Apple Speech Framework, and processes them through a sophisticated multi-agent system built with LangChain and LangGraph. The system intelligently classifies user intent, manages task lifecycles, and provides deep productivity analytics to help users understand their work patterns.

## Tech Stack

**Backend**
- Flask + Python
- LangChain & LangGraph for multi-agent orchestration
- Firebase Authentication & Firestore
- OpenAI GPT models
- WebSocket for real-time communication
- LangSmith for monitoring and observability

**Frontend**
- Flutter (iOS)
- Apple Speech Framework for on-device transcription
- Firebase Auth with Google Sign-In
- WebSocket client for live updates

## Key Features

### Core Task Management
- **Voice-to-Text**: On-device transcription using Apple Speech Framework
- **Intent Classification**: Multi-agent system detects user intent (create, edit, complete, delete)
- **Smart Organization**: Automatically assigns tasks to correct folders or respects user-specified categorization
- **Task Operations**: Complete/incomplete marking, editing, deletion based on voice commands
- **Intelligent Scheduling**: Context-aware due date and priority assignment

### Advanced Analytics
- **Productivity Insights**: Analysis agent tracks completion patterns and procrastination tendencies
- **Performance Metrics**: 
  - Task completion rates
  - Tasks behind schedule
  - Most frequently missed tasks by due date and priority
  - Peak productivity hours and timings
  - Day-of-week performance patterns
- **Stale Task Monitoring**: Automatically detects tasks idle for 7+ days and prompts action

### System Optimization
- **Eval Dataset**: Tracks agent failures and hallucinations
- **Prompt Engineering**: Few-shot prompting and optimized system prompts
- **LangSmith Integration**: Monitors LLM token costs, latency per node, and response times
- **Real-time Updates**: WebSocket-based synchronization
  
## Architecture Flow

1. **Voice Input**: User speaks task details or questions into Flutter mobile app
2. **On-Device Transcription**: Apple Speech Framework converts speech to text in real-time
3. **Multi-Agent Processing**: Text sent to Flask backend, processed through LangGraph workflow:
   - **Memory Extraction Node**: 
     - Extracts user preferences from current input
     - Pulls relevant context from PostgreSQL (existing tasks, preferences, folder structures)
   - **Router Node**: Analyzes intent and routes to appropriate agent:
     - Routes to CRUD for task operations (create/edit/complete/delete/organize)
     - Routes to Analysis for productivity insights and pattern queries
   - **CRUD Node**: Handles all task management operations:
     - Task creation with intelligent scheduling
     - Editing task details, due dates, priorities
     - Marking tasks complete/incomplete
     - Deleting tasks
     - Folder assignment and categorization
   - **Analysis Node**: Processes productivity insight queries:
     - Completion pattern analysis
     - Peak productivity hours/days identification
     - Procrastination trends detection
     - Task performance metrics
     - Stale task monitoring (7+ days idle)
4. **State Management**: 
   - PostgreSQL: Persistent storage for tasks, user preferences, and analytics data
   - SQLite Checkpointer: LangGraph state persistence for multi-turn conversations
   - Firebase: Real-time task synchronization to mobile app
   - WebSocket: Live updates pushed to Flutter frontend
   

## Challenges Solved

- **LLM Hallucination Mitigation**: Eval datasets and few-shot prompting to reduce errors
- **Intent Accuracy**: Multi-agent architecture for precise task operation detection   
- **Productivity Analytics**: Pattern detection across time dimensions (hourly, daily, weekly)
- **Cost Optimization**: LangSmith monitoring for token usage and latency tracking


