# evals/eval_router.py

import sys
import os
from typing import Dict, List
from datetime import datetime
import json
import time

# Add parent directory (backend/) to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

# Change working directory to backend (for Firebase credentials)
os.chdir(backend_dir)

# ===== FORCE SQLITE MODE FOR EVALS =====
os.environ['USE_SQLITE'] = 'true'

print(f"🔍 Backend directory: {backend_dir}")
print(f"🔍 Working directory: {os.getcwd()}")
print(f"🔍 Database mode: SQLite (eval mode)")

# NOW import voicelog (after setting USE_SQLITE)
from agents.voicelog_graph import voicelog_app
from evals.routing_dataset import ROUTING_TEST_CASES

class RouterEvaluator:
    """Evaluate VoiceLog router node decisions"""
    
    def __init__(self):
        self.app = voicelog_app
        self.results = []
    
    def extract_routing_decision(self, graph_state: Dict) -> str:
        """
        Extract which route the router chose.
        Your router returns {"route_decision": "crud" | "analysis"}
        """
        return graph_state.get("route_decision", "unknown")
    
    def run_single_test(self, test_case: Dict, user_id: str = "eval_user") -> Dict:
        """Run a single routing test - STREAM and stop after router"""
        
        try:
            result_state = None
            
            # Stream through graph nodes one at a time
            for event in self.app.stream(
                {
                    "user_command": test_case["input"],
                    "messages": [],
                    "user_timezone": "America/Los_Angeles"
                },
                config={
                    "configurable": {
                        "thread_id": f"eval_{test_case['id']}",
                        "user_id": user_id
                    }
                },
                stream_mode="updates"  # Get updates for each node
            ):
                # event is a dict like: {"router": {...state after router...}}
                
                # If we just finished the router node, capture state and stop
                if "router" in event:
                    result_state = event["router"]
                    print(f"    🎯 Router decision captured: {result_state.get('route_decision')}")
                    break  # STOP STREAMING - don't let it enter CRUD/Analysis
            
            if result_state is None:
                raise Exception("Router didn't produce output in stream")
            
            actual_route = self.extract_routing_decision(result_state)
            expected_route = test_case["expected_route"]
            
            passed = actual_route == expected_route
            
            return {
                "test_id": test_case["id"],
                "input": test_case["input"],
                "expected": expected_route,
                "actual": actual_route,
                "passed": passed,
                "reasoning": test_case.get("reasoning", "")
            }
            
        except Exception as e:
            # Handle rate limits with retry
            error_str = str(e).lower()
            if ("rate_limit" in error_str or "429" in error_str or 
                "quota" in error_str or "insufficient_quota" in error_str):
                print(f"    ⏳ OpenAI quota/rate limit hit - skipping remaining tests")
                print(f"    💡 Fix: Add credits at https://platform.openai.com/account/billing")
                raise  # Re-raise to stop the test run
            
            import traceback
            return {
                "test_id": test_case["id"],
                "input": test_case["input"],
                "expected": test_case["expected_route"],
                "actual": "ERROR",
                "passed": False,
                "error": str(e)[:200],
                "reasoning": test_case.get("reasoning", "")
            }
    
    def run_all_tests(self, test_cases: List[Dict] = None):
        """Run all routing tests with delays to avoid rate limits"""
        if test_cases is None:
            test_cases = ROUTING_TEST_CASES
        
        print(f"\n{'='*80}")
        print(f"🧪 VOICELOG ROUTER EVALUATION")
        print(f"{'='*80}")
        print(f"Running {len(test_cases)} test cases...\n")
        
        self.results = []
        
        for i, test in enumerate(test_cases, 1):
            print(f"[{i}/{len(test_cases)}] Testing: {test['input'][:60]}...")
            
            try:
                result = self.run_single_test(test)
                self.results.append(result)
                
                # Print result
                status = "✅" if result["passed"] else "❌"
                print(f"    {status} Expected: {result['expected']} | Got: {result['actual']}")
                
                if not result["passed"]:
                    print(f"    📝 Context: {result['reasoning']}")
                    if "error" in result:
                        print(f"    ⚠️  Error: {result['error'][:100]}...")
                    print()
                
                # Add delay between tests (except last test)
                if i < len(test_cases):
                    time.sleep(2)
                    
            except Exception as e:
                # If quota exceeded, stop all tests
                if "quota" in str(e).lower() or "insufficient_quota" in str(e).lower():
                    print(f"\n❌ STOPPING: OpenAI quota exceeded")
                    print(f"💡 Add credits at: https://platform.openai.com/account/billing")
                    print(f"📊 Completed {i-1}/{len(test_cases)} tests before quota limit\n")
                    break
                else:
                    raise
        
        if len(self.results) > 0:
            self.print_summary()
        
        return self.results
    
    def print_summary(self):
        """Print comprehensive evaluation summary"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        accuracy = (passed / total * 100) if total > 0 else 0
        
        print(f"\n{'='*80}")
        print(f"📊 EVALUATION SUMMARY")
        print(f"{'='*80}")
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed} ({accuracy:.1f}%)")
        print(f"❌ Failed: {failed}")
        
        # Breakdown by expected route
        route_stats = {}
        for result in self.results:
            route = result["expected"]
            if route not in route_stats:
                route_stats[route] = {"total": 0, "passed": 0, "failed_cases": []}
            route_stats[route]["total"] += 1
            if result["passed"]:
                route_stats[route]["passed"] += 1
            else:
                route_stats[route]["failed_cases"].append(result)
        
        print(f"\n📈 Breakdown by Route:")
        for route, stats in route_stats.items():
            acc = (stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
            print(f"  {route.upper()}: {stats['passed']}/{stats['total']} ({acc:.1f}%)")
        
        # Show failed cases
        if failed > 0:
            print(f"\n❌ Failed Cases:")
            for result in self.results:
                if not result["passed"]:
                    print(f"  • {result['test_id']}: \"{result['input']}\"")
                    print(f"    Expected: {result['expected']} | Got: {result['actual']}")
                    print(f"    Reason: {result['reasoning']}\n")
        
        print(f"{'='*80}\n")
    
    def save_results(self, filepath: str = None):
        """Save results to JSON file"""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("evals/results", exist_ok=True)
            filepath = f"evals/results/router_eval_{timestamp}.json"
        
        with open(filepath, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "test_set": "small",
                "total_tests": len(self.results),
                "passed": sum(1 for r in self.results if r["passed"]),
                "failed": sum(1 for r in self.results if not r["passed"]),
                "accuracy": sum(1 for r in self.results if r["passed"]) / len(self.results) if self.results else 0,
                "results": self.results
            }, f, indent=2)
        
        print(f"💾 Results saved to {filepath}")
        return filepath


# Run the evaluation
if __name__ == "__main__":
    print("\n🚀 Starting VoiceLog Router Evaluation (Small Test Set)...\n")
    
    evaluator = RouterEvaluator()
    results = evaluator.run_all_tests()
    
    if len(results) == 0:
        print("\n❌ No tests completed - check OpenAI credits")
        sys.exit(1)
    
    # Save results
    filepath = evaluator.save_results()
    
    # Exit with error code if accuracy below threshold
    accuracy = sum(1 for r in results if r["passed"]) / len(results) if results else 0
    THRESHOLD = 0.85  # 85% minimum accuracy
    
    if accuracy < THRESHOLD:
        print(f"\n⚠️  WARNING: Accuracy {accuracy:.1%} is below {THRESHOLD:.0%} threshold")
        print(f"👉 Review failed cases and improve router prompt")
        sys.exit(1)
    else:
        print(f"\n✅ SUCCESS: Accuracy {accuracy:.1%} meets {THRESHOLD:.0%} threshold")
        print(f"👉 Ready to test on full dataset (36 cases)")
        sys.exit(0)