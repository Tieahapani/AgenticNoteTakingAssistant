"""
ReAct Agent Debugger - Stream agent thoughts in real-time
"""

from typing import Any, Dict
from langchain_core.callbacks import BaseCallbackHandler


class ReActDebugCallback(BaseCallbackHandler):
    """Callback to print ReAct agent's reasoning process in real-time"""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.step_count = 0

    def on_llm_start(self, serialized: Dict[str, Any], prompts: list, **kwargs) -> None:
        """Called when LLM starts thinking"""
        if self.verbose:
            self.step_count += 1
            print(f"\n{'='*60}")
            print(f"💭 STEP {self.step_count}: AGENT THINKING...")
            print(f"{'='*60}")

    def on_llm_end(self, response, **kwargs) -> None:
        """Called when LLM finishes thinking"""
        if self.verbose:
            # Extract the thought/decision
            if hasattr(response, 'generations') and response.generations:
                text = response.generations[0][0].text

                # Check if it's a tool call or final answer
                if "Action:" in text or "tool_calls" in str(response):
                    print(f"🎯 DECISION: Will call a tool")
                else:
                    print(f"✅ DECISION: Ready to respond to user")

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """Called when agent decides to use a tool"""
        if self.verbose:
            tool_name = serialized.get("name", "unknown")
            print(f"\n🔧 ACTION: Calling tool '{tool_name}'")
            print(f"📥 INPUT: {input_str[:200]}")

    def on_tool_end(self, output: str, **kwargs) -> None:
        """Called when tool returns result"""
        if self.verbose:
            print(f"📤 OUTPUT: {str(output)[:200]}...")
            print(f"👀 OBSERVATION: Agent now processing this result...")

    def on_agent_action(self, action, **kwargs) -> None:
        """Called when agent takes an action"""
        if self.verbose:
            print(f"\n🎬 AGENT ACTION:")
            print(f"   Tool: {action.tool}")
            print(f"   Input: {action.tool_input}")

    def on_agent_finish(self, finish, **kwargs) -> None:
        """Called when agent finishes"""
        if self.verbose:
            print(f"\n{'='*60}")
            print(f"🏁 AGENT FINISHED")
            print(f"   Return: {str(finish.return_values)[:150]}")
            print(f"{'='*60}\n")

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain starts"""
        if self.verbose and "agent" in str(serialized.get("name", "")).lower():
            print(f"\n🚀 REACT LOOP STARTING")
            print(f"   Input: {str(inputs)[:150]}")

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain ends"""
        pass  # Less verbose to avoid clutter


def create_debug_callback(verbose: bool = True) -> ReActDebugCallback:
    """Factory function to create debug callback"""
    return ReActDebugCallback(verbose=verbose)
