# evals/memory_dataset.py

MEMORY_TEST_CASES = [
    {
        "id": "MEM001", 
        "input": "I always workout in the morning before 8 am", 
        "expected_extract": True, 
        "expected_preferences": [  # Fixed typo: was "expected_preference"
            {
                "contains": "morning workout before 8 am", 
                "confidence": "high", 
                "type": "habit"
            }
        ], 
        "reasoning": "clear routine/habit statement"
    }, 
    {
        "id": "MEM002", 
        "input": "All my AI-related tasks should go in the Problems folder", 
        "expected_extract": True,
        "expected_preferences": [
            {
                "contains": ["AI tasks", "Problems folder"],  # Multiple contains as list
                "confidence": "high",
                "type": "organizational_rule"
            }
        ],
        "reasoning": "Explicit folder routing rule"
    }, 
    {
        "id": "MEM003",
        "input": "I'm a software engineer at Google working on ML infrastructure",
        "expected_extract": True,
        "expected_preferences": [
            {
                "contains": ["software engineer", "Google"],
                "confidence": "high",
                "type": "personal_fact"
            }
        ],
        "reasoning": "Personal/professional information"
    },
    {
        "id": "MEM004", 
        "input": "I live in San Francisco and work from home on Fridays", 
        "expected_extract": True,
        "expected_preferences": [
            {
                "contains": "San Francisco",
                "confidence": "high",
                "type": "location"
            },
            {
                "contains": ["work from home", "Friday"],
                "confidence": "high",
                "type": "work_pattern"
            }
        ],
        "reasoning": "Location + routine information"
    },
    
    # Should NOT extract - one-time commands
    {
        "id": "MEM005",
        "input": "Add buy groceries to my tasks",
        "expected_extract": False,
        "expected_preferences": [],
        "reasoning": "One-time task creation command"
    },
    {
        "id": "MEM006",
        "input": "Delete the dentist appointment",
        "expected_extract": False,
        "expected_preferences": [],
        "reasoning": "One-time action on specific task"
    },
    {
        "id": "MEM007",
        "input": "How am I doing this week?",
        "expected_extract": False,
        "expected_preferences": [],
        "reasoning": "Analysis/insight request"
    },
    {
        "id": "MEM008",
        "input": "What tasks do I have today?",
        "expected_extract": False,
        "expected_preferences": [],
        "reasoning": "Query about current state"
    }, 
    {
        "id": "MEM009", 
        "input": "Remind me to call mom on Sunday", 
        "expected_extract": False, 
        "expected_preferences": [], 
        "reasoning": "It is a one-time reminder setup"
    }, 
    {
        "id": "MEM010", 
        "input": "Schedule a meeting with the team for next Monday", 
        "expected_extract": False, 
        "expected_preferences": [], 
        "reasoning": "A reminder schedule again"
    }, 
    {
        "id": "MEMO11", 
        "input": "I think I have a problem with schedule, can you shift my meetings around?", 
        "expected_extract": False, 
        "expected_preferences": [], 
        "reasoning": "It is a request for assistance"
    }, 
{
    "id": "MEM012", 
    "input": "How can I become the best at what I do?", 
    "expected_extract": False, 
    "expected_preferences" : [], 
    "reasoning": "A statement"

    
}
]