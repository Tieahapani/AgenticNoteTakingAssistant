# evals/eval_memory.py

import sys
import os
from typing import Dict, List
from datetime import datetime
import json
import time

# Add parent directory (backend/) to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

# Change working directory to backend
os.chdir(backend_dir)

# ===== FORCE SQLITE MODE FOR EVALS =====
os.environ['USE_SQLITE'] = 'true'

print(f"🔍 Backend directory: {backend_dir}")
print(f"🔍 Working directory: {os.getcwd()}")
print(f"🔍 Database mode: SQLite (eval mode)")

# Import after setting env
from agents.voicelog_graph import voicelog_app
from evals.memory_dataset import MEMORY_TEST_CASES

class MemoryEvaluator:
    """Evaluate VoiceLog memory extraction node"""
    
    def __init__(self):
        self.app = voicelog_app
        self.results = []
    
    def check_preference_match(self, actual_pref: Dict, expected_pref: Dict) -> bool:
        """
        Check if an actual extracted preference matches expected criteria.
        
        Expected format:
        {
            "contains": "keyword" or ["keyword1", "keyword2"],
            "confidence": "high",
            "type": "habit"
        }
        """
        pref_text = actual_pref.get("pref", "").lower()
        
        # Check "contains" field
        contains = expected_pref.get("contains", "")
        if isinstance(contains, str):
            contains = [contains]
        
        # All keywords must be present
        for keyword in contains:
            if keyword.lower() not in pref_text:
                return False
        
        # Check confidence if specified
        if "confidence" in expected_pref:
            if actual_pref.get("confidence") != expected_pref["confidence"]:
                return False
        
        return True
    
    def evaluate_extraction(self, actual_memories: List[Dict], expected_prefs: List[Dict]) -> Dict:
        """
        Evaluate if extracted memories match expectations.
        
        Returns:
        {
            "matched": True/False,
            "score": 0.0-1.0,
            "details": "explanation"
        }
        """
        # If we expect NO extraction
        if len(expected_prefs) == 0:
            if len(actual_memories) == 0:
                return {
                    "matched": True,
                    "score": 1.0,
                    "details": "Correctly extracted nothing"
                }
            else:
                return {
                    "matched": False,
                    "score": 0.0,
                    "details": f"Expected no extraction, but got {len(actual_memories)} preferences"
                }
        
        # If we expect extraction
        matched_count = 0
        
        for expected_pref in expected_prefs:
            # Check if ANY actual preference matches this expected one
            found_match = False
            for actual_pref in actual_memories:
                if self.check_preference_match(actual_pref, expected_pref):
                    found_match = True
                    break
            
            if found_match:
                matched_count += 1
        
        score = matched_count / len(expected_prefs) if expected_prefs else 0.0
        
        return {
            "matched": matched_count == len(expected_prefs),
            "score": score,
            "details": f"Matched {matched_count}/{len(expected_prefs)} expected preferences"
        }
    
    def run_single_test(self, test_case: Dict, user_id: str = "eval_memory_user") -> Dict:
        """Run a single memory extraction test"""
        
        try:
            result_state = None
            
            # Stream through graph and capture memory extraction output
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
                stream_mode="updates"
            ):
                # Capture state after memory extraction node
                if "extract_memory" in event:
                    result_state = event["extract_memory"]
                    print(f"    🧠 Memory extraction completed")
                    break  # Stop after memory node
            
            if result_state is None:
                raise Exception("Memory extraction node didn't produce output")
            
            # Get extracted memories
            actual_memories = result_state.get("new_memories", [])
            expected_extract = test_case["expected_extract"]
            expected_prefs = test_case.get("expected_preferences", [])
            
            # Evaluate
            evaluation = self.evaluate_extraction(actual_memories, expected_prefs)
            
            return {
                "test_id": test_case["id"],
                "input": test_case["input"],
                "expected_extract": expected_extract,
                "actual_extracted": len(actual_memories) > 0,
                "expected_count": len(expected_prefs),
                "actual_count": len(actual_memories),
                "actual_memories": actual_memories,
                "matched": evaluation["matched"],
                "score": evaluation["score"],
                "details": evaluation["details"],
                "reasoning": test_case.get("reasoning", "")
            }
            
        except Exception as e:
            # Handle quota errors
            error_str = str(e).lower()
            if ("quota" in error_str or "insufficient_quota" in error_str or 
                "rate_limit" in error_str or "429" in error_str):
                print(f"    ⏳ OpenAI quota/rate limit hit")
                raise
            
            return {
                "test_id": test_case["id"],
                "input": test_case["input"],
                "expected_extract": test_case["expected_extract"],
                "actual_extracted": False,
                "matched": False,
                "score": 0.0,
                "error": str(e)[:200],
                "reasoning": test_case.get("reasoning", "")
            }
    
    def run_all_tests(self, test_cases: List[Dict] = None):
        """Run all memory extraction tests"""
        if test_cases is None:
            test_cases = MEMORY_TEST_CASES
        
        print(f"\n{'='*80}")
        print(f"🧠 VOICELOG MEMORY EXTRACTION EVALUATION")
        print(f"{'='*80}")
        print(f"Running {len(test_cases)} test cases...\n")
        
        self.results = []
        
        for i, test in enumerate(test_cases, 1):
            print(f"[{i}/{len(test_cases)}] Testing: {test['input'][:60]}...")
            
            try:
                result = self.run_single_test(test)
                self.results.append(result)
                
                # Print result
                status = "✅" if result["matched"] else "❌"
                print(f"    {status} Extract: {result['expected_extract']} | Got: {result['actual_extracted']}")
                print(f"    📊 Score: {result['score']:.0%} - {result.get('details', '')}")
                
                if not result["matched"]:
                    print(f"    📝 Context: {result['reasoning']}")
                    if "actual_memories" in result and result["actual_memories"]:
                        print(f"    🔍 Extracted: {result['actual_memories']}")
                    if "error" in result:
                        print(f"    ⚠️  Error: {result['error'][:100]}...")
                    print()
                
                # Delay between tests
                if i < len(test_cases):
                    time.sleep(2)
                    
            except Exception as e:
                # If quota exceeded, stop
                if "quota" in str(e).lower() or "insufficient_quota" in str(e).lower():
                    print(f"\n❌ STOPPING: OpenAI quota exceeded")
                    print(f"📊 Completed {i-1}/{len(test_cases)} tests\n")
                    break
                else:
                    raise
        
        if len(self.results) > 0:
            self.print_summary()
        
        return self.results
    
    def print_summary(self):
        """Print evaluation summary"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["matched"])
        failed = total - passed
        avg_score = sum(r["score"] for r in self.results) / total if total > 0 else 0
        
        print(f"\n{'='*80}")
        print(f"📊 EVALUATION SUMMARY")
        print(f"{'='*80}")
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed} ({passed/total*100:.1f}%)")
        print(f"❌ Failed: {failed}")
        print(f"📈 Average Score: {avg_score:.1%}")
        
        # Breakdown by extraction expectation
        should_extract = [r for r in self.results if r["expected_extract"]]
        should_not = [r for r in self.results if not r["expected_extract"]]
        
        print(f"\n📈 Breakdown:")
        if should_extract:
            passed_extract = sum(1 for r in should_extract if r["matched"])
            print(f"  Should Extract: {passed_extract}/{len(should_extract)} ({passed_extract/len(should_extract)*100:.1f}%)")
        if should_not:
            passed_not = sum(1 for r in should_not if r["matched"])
            print(f"  Should NOT Extract: {passed_not}/{len(should_not)} ({passed_not/len(should_not)*100:.1f}%)")
        
        # Show failed cases
        if failed > 0:
            print(f"\n❌ Failed Cases:")
            for result in self.results:
                if not result["matched"]:
                    print(f"  • {result['test_id']}: \"{result['input']}\"")
                    print(f"    Expected: {'Extract' if result['expected_extract'] else 'No extract'}")
                    print(f"    Got: {'Extracted' if result['actual_extracted'] else 'No extraction'}")
                    if "actual_memories" in result and result["actual_memories"]:
                        print(f"    Memories: {result['actual_memories']}")
                    print(f"    Reason: {result['reasoning']}\n")
        
        print(f"{'='*80}\n")
    
    def save_results(self, filepath: str = None):
        """Save results to JSON file"""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("evals/results", exist_ok=True)
            filepath = f"evals/results/memory_eval_{timestamp}.json"
        
        with open(filepath, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "total_tests": len(self.results),
                "passed": sum(1 for r in self.results if r["matched"]),
                "failed": sum(1 for r in self.results if not r["matched"]),
                "average_score": sum(r["score"] for r in self.results) / len(self.results) if self.results else 0,
                "results": self.results
            }, f, indent=2)
        
        print(f"💾 Results saved to {filepath}")
        return filepath


# Run the evaluation
if __name__ == "__main__":
    print("\n🚀 Starting VoiceLog Memory Extraction Evaluation...\n")
    
    evaluator = MemoryEvaluator()
    results = evaluator.run_all_tests()
    
    if len(results) == 0:
        print("\n❌ No tests completed - check OpenAI credits")
        sys.exit(1)
    
    # Save results
    filepath = evaluator.save_results()
    
    # Exit with error code if average score below threshold
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0
    THRESHOLD = 0.80  # 80% minimum score
    
    if avg_score < THRESHOLD:
        print(f"\n⚠️  WARNING: Average score {avg_score:.1%} is below {THRESHOLD:.0%} threshold")
        print(f"👉 Review failed cases and improve memory extraction prompt")
        sys.exit(1)
    else:
        print(f"\n✅ SUCCESS: Average score {avg_score:.1%} meets {THRESHOLD:.0%} threshold")
        sys.exit(0)