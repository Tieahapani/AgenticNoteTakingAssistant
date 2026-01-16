# utils/timing.py

import time
import json
from datetime import datetime
from pathlib import Path

class LatencyTracker:
    def __init__(self):
        self.timings = {}
        
    def start(self, operation):
        self.timings[operation] = {"start": time.time()}
        
    def end(self, operation):
        if operation in self.timings:
            end_time = time.time()
            start_time = self.timings[operation]["start"]
            latency = end_time - start_time
            self.timings[operation]["latency"] = latency
            print(f"⏱️  {operation}: {latency:.2f}s")
            return latency
        return 0
    
    def get_summary(self):
        total = sum(t.get("latency", 0) for t in self.timings.values())
        return {
            "total_time": round(total, 2),
            "operations": {
                op: round(data.get("latency", 0), 2) 
                for op, data in self.timings.items()
            }
        }
    
    def log_to_file(self, user_command, response):
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "command": user_command[:100],
            "response": response[:100],
            "timings": self.get_summary()
        }
        
        log_file = log_dir / f"latency_{datetime.now().date()}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")