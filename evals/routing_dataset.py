# voicelog/evals/routing_dataset.py

ROUTING_TEST_CASES = [
    # ===== CRUD: Task Creation =====
    {
        "id": "RT001",
        "input": "Add buy groceries to my list",
        "expected_route": "crud",
        "reasoning": "Creating a new task"
    },

    {
        "id": "RT004",
        "input": "Tell me what is there in my Work folder",
        "expected_route": "crud",
        "reasoning": "Viewing a folder"
    },
    
    # ===== CRUD: Task Status Changes =====
    {
        "id": "RT005",
        "input": "I'm done with my workout and I need to set up a daily routine for that",
        "expected_route": "crud",
        "reasoning": "Marking task complete"
    },
    {
        "id": "RT006",
        "input": "Mark the grocery task as complete",
        "expected_route": "crud",
        "reasoning": "Explicit complete action"
    },
    {
        "id": "RT007",
        "input": "I finished reading the book",
        "expected_route": "crud",
        "reasoning": "Implicit task completion"
    },
    
    # ===== CRUD: Task Modifications =====
    {
        "id": "RT008",
        "input": "Delete the dentist appointment",
        "expected_route": "crud",
        "reasoning": "Deleting a task"
    },
    {
        "id": "RT009",
        "input": "Move the grocery task to Shopping folder",
        "expected_route": "crud",
        "reasoning": "Moving task between folders"
    },
    {
        "id": "RT010",
        "input": "Change the project deadline to next Monday",
        "expected_route": "crud",
        "reasoning": "Editing task details"
    },
   
    
    # ===== EDGE CASES: Temporal Markers =====
   
    {
        "id": "RT035",
        "input": "Have I been failing with completing tasks?",
        "expected_route": "analysis",
        "reasoning": "performance"
    },
    {
        "id": "RT036",
        "input": "What time of the day am I most productive?",
        "expected_route": "crud",
        "reasoning": "Future/current - task list"
    },
]