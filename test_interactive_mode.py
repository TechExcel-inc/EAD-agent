#!/usr/bin/env python3
"""
Test script for interactive mode functionality.

This script performs basic tests to verify that the interactive mode
modifications work correctly without requiring a full agent run.
"""

import sys
import os

# Add the parent directory to the path so we can import run_agent
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_agent import AIAgent


def test_interactive_mode_initialization():
    """Test that interactive mode parameters are properly initialized."""
    print("Test 1: Interactive Mode Initialization")

    # Test with interactive mode enabled
    agent1 = AIAgent(
        model="test-model",
        interactive_mode=True,
        summary_interval=5,
    )

    assert agent1.interactive_mode == True, "interactive_mode should be True"
    assert agent1.summary_interval == 5, "summary_interval should be 5"
    print("✓ Interactive mode enabled correctly")

    # Test with interactive mode disabled (default)
    agent2 = AIAgent(
        model="test-model",
        interactive_mode=False,
    )

    assert agent2.interactive_mode == False, "interactive_mode should be False"
    assert agent2.summary_interval == 5, "summary_interval should default to 5"
    print("✓ Interactive mode disabled correctly")

    # Test default values
    agent3 = AIAgent(model="test-model")

    assert agent3.interactive_mode == False, "interactive_mode should default to False"
    assert agent3.summary_interval == 5, "summary_interval should default to 5"
    print("✓ Default values correct")

    print("Test 1: PASSED\n")


def test_checkpoint_methods():
    """Test that checkpoint helper methods work correctly."""
    print("Test 2: Checkpoint Helper Methods")

    agent = AIAgent(
        model="test-model",
        interactive_mode=True,
        summary_interval=5,
    )

    # Test should_pause_for_interactive_checkpoint
    assert agent.should_pause_for_interactive_checkpoint(5) == True, "Should pause at iteration 5"
    assert agent.should_pause_for_interactive_checkpoint(10) == True, "Should pause at iteration 10"
    assert agent.should_pause_for_interactive_checkpoint(3) == False, "Should not pause at iteration 3"
    assert agent.should_pause_for_interactive_checkpoint(0) == False, "Should not pause at iteration 0"
    print("✓ should_pause_for_interactive_checkpoint works correctly")

    # Test format_interactive_checkpoint_message
    message = agent.format_interactive_checkpoint_message(
        10,
        ["browser", "read_file", "write_file"]
    )

    assert "Iteration 10" in message, "Message should contain iteration count"
    assert "browser" in message, "Message should contain tool names"
    assert "read_file" in message, "Message should contain tool names"
    assert "write_file" in message, "Message should contain tool names"
    assert "continue" in message.lower(), "Message should mention continue option"
    assert "stop" in message.lower(), "Message should mention stop option"
    print("✓ format_interactive_checkpoint_message works correctly")

    print("Test 2: PASSED\n")


def test_disabled_mode():
    """Test that checkpoints don't trigger when interactive mode is disabled."""
    print("Test 3: Disabled Mode Behavior")

    agent = AIAgent(
        model="test-model",
        interactive_mode=False,  # Disabled
        summary_interval=5,
    )

    # Even at interval boundaries, should not pause
    assert agent.should_pause_for_interactive_checkpoint(5) == False, "Should not pause when disabled"
    assert agent.should_pause_for_interactive_checkpoint(10) == False, "Should not pause when disabled"
    print("✓ Checkpoints correctly bypassed when disabled")

    print("Test 3: PASSED\n")


def test_custom_intervals():
    """Test various custom interval configurations."""
    print("Test 4: Custom Interval Configurations")

    # Test interval of 3
    agent1 = AIAgent(
        model="test-model",
        interactive_mode=True,
        summary_interval=3,
    )

    assert agent1.should_pause_for_interactive_checkpoint(3) == True
    assert agent1.should_pause_for_interactive_checkpoint(6) == True
    assert agent1.should_pause_for_interactive_checkpoint(9) == True
    assert agent1.should_pause_for_interactive_checkpoint(4) == False
    print("✓ Interval of 3 works correctly")

    # Test interval of 10
    agent2 = AIAgent(
        model="test-model",
        interactive_mode=True,
        summary_interval=10,
    )

    assert agent2.should_pause_for_interactive_checkpoint(10) == True
    assert agent2.should_pause_for_interactive_checkpoint(20) == True
    assert agent2.should_pause_for_interactive_checkpoint(5) == False
    assert agent2.should_pause_for_interactive_checkpoint(15) == False
    print("✓ Interval of 10 works correctly")

    print("Test 4: PASSED\n")


def test_message_formatting():
    """Test message formatting with various scenarios."""
    print("Test 5: Message Formatting Edge Cases")

    agent = AIAgent(
        model="test-model",
        interactive_mode=True,
        summary_interval=5,
    )

    # Empty tool list
    message1 = agent.format_interactive_checkpoint_message(5, [])
    assert "Iteration 5" in message1
    assert "Recent Actions" not in message1 or "🔧" not in message1
    print("✓ Handles empty tool list correctly")

    # Large iteration count
    message2 = agent.format_interactive_checkpoint_message(1000, ["test_tool"])
    assert "Iteration 1000" in message2
    print("✓ Handles large iteration counts")

    # Special characters in tool names
    message3 = agent.format_interactive_checkpoint_message(
        5,
        ["tool-with-dash", "tool_with_underscore", "tool.with.dots"]
    )
    assert "tool-with-dash" in message3
    assert "tool_with_underscore" in message3
    assert "tool.with.dots" in message3
    print("✓ Handles special characters in tool names")

    print("Test 5: PASSED\n")


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 70)
    print("INTERACTIVE MODE TEST SUITE")
    print("=" * 70)
    print()

    try:
        test_interactive_mode_initialization()
        test_checkpoint_methods()
        test_disabled_mode()
        test_custom_intervals()
        test_message_formatting()

        print("=" * 70)
        print("ALL TESTS PASSED ✓")
        print("=" * 70)
        print()
        print("The interactive mode modifications are working correctly!")
        print()
        print("Next steps:")
        print("1. Try the example: python interactive_example.py")
        print("2. Read the docs: cat INTERACTIVE_MODE.md")
        print("3. Integrate into your workflow")
        print()

        return 0

    except AssertionError as e:
        print()
        print("=" * 70)
        print("TEST FAILED ✗")
        print("=" * 70)
        print(f"Error: {e}")
        print()
        return 1

    except Exception as e:
        print()
        print("=" * 70)
        print("TEST ERROR ✗")
        print("=" * 70)
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        print()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
