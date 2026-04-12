#!/usr/bin/env python3
"""
Example: Using EAD-Agent in Interactive Mode

This example demonstrates how to use the AI agent with interactive mode enabled,
which causes the agent to pause every N iterations (default: 5) to summarize
progress and wait for user confirmation before proceeding.

Usage:
    python interactive_example.py

The agent will:
1. Execute the task using available tools
2. Every 5 iterations, pause and show a progress checkpoint
3. Wait for your input (continue/stop/new instructions)
4. Resume or modify execution based on your feedback
"""

import sys
import os

# Add the parent directory to the path so we can import run_agent
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_agent import AIAgent


def main():
    """Run an example agent in interactive mode."""

    # Example task: Explore the current directory and understand the codebase
    task = """
    Explore this codebase and provide a summary of:
    1. What programming languages are used
    2. The main purpose of this project
    3. Key components and their relationships
    4. Any interesting patterns or architectures

    Start by listing the directory structure and examining key files.
    """

    print("🤖 Starting AI Agent in Interactive Mode")
    print("=" * 60)
    print(f"Task: {task.strip()}")
    print("=" * 60)
    print()

    # Initialize the agent with interactive mode enabled
    agent = AIAgent(
        model="claude-opus-4-6",  # Or your preferred model
        interactive_mode=True,    # Enable interactive mode
        summary_interval=5,       # Pause every 5 iterations
        max_iterations=30,        # Limit total iterations for this example
        verbose_logging=False,    # Set to True for detailed debugging
        quiet_mode=False,         # Show progress messages
    )

    # Run the conversation
    result = agent.run_conversation(
        user_message=task,
    )

    # Display results
    print()
    print("=" * 60)
    print("🎯 Agent Execution Complete")
    print("=" * 60)
    print(f"Status: {'✅ Success' if result.get('completed') else '⚠️ Incomplete'}")
    print(f"API Calls: {result.get('api_calls', 0)}")
    print(f"Final Response: {result.get('final_response', 'No response')[:200]}...")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Execution interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
