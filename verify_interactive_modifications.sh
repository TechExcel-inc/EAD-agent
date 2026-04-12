#!/bin/bash
# Verification script for interactive mode modifications
# This script verifies that the modifications were applied correctly

echo "======================================================================"
echo "INTERACTIVE MODE MODIFICATION VERIFICATION"
echo "======================================================================"
echo ""

# Check if the run_agent.py file exists
if [ ! -f "run_agent.py" ]; then
    echo "✗ ERROR: run_agent.py not found"
    exit 1
fi
echo "✓ Found run_agent.py"
echo ""

# Check for interactive_mode parameter
if grep -q "interactive_mode: bool = False" run_agent.py; then
    echo "✓ Found interactive_mode parameter in __init__"
else
    echo "✗ ERROR: interactive_mode parameter not found"
    exit 1
fi

# Check for summary_interval parameter
if grep -q "summary_interval: int = 5" run_agent.py; then
    echo "✓ Found summary_interval parameter in __init__"
else
    echo "✗ ERROR: summary_interval parameter not found"
    exit 1
fi

# Check for should_pause_for_interactive_checkpoint method
if grep -q "def should_pause_for_interactive_checkpoint" run_agent.py; then
    echo "✓ Found should_pause_for_interactive_checkpoint method"
else
    echo "✗ ERROR: should_pause_for_interactive_checkpoint method not found"
    exit 1
fi

# Check for format_interactive_checkpoint_message method
if grep -q "def format_interactive_checkpoint_message" run_agent.py; then
    echo "✓ Found format_interactive_checkpoint_message method"
else
    echo "✗ ERROR: format_interactive_checkpoint_message method not found"
    exit 1
fi

# Check for interactive checkpoint logic in the main loop
if grep -q "should_pause_for_interactive_checkpoint(api_call_count)" run_agent.py; then
    echo "✓ Found interactive checkpoint logic in execution loop"
else
    echo "✗ ERROR: Interactive checkpoint logic not found in execution loop"
    exit 1
fi

# Check for Progress Checkpoint message
if grep -q "Progress Checkpoint" run_agent.py; then
    echo "✓ Found checkpoint message formatting"
else
    echo "✗ ERROR: Checkpoint message formatting not found"
    exit 1
fi

echo ""
echo "======================================================================"
echo "VERIFICATION COMPLETE - ALL CHECKS PASSED ✓"
echo "======================================================================"
echo ""
echo "Summary of modifications:"
echo "  • Added interactive_mode parameter (default: False)"
echo "  • Added summary_interval parameter (default: 5)"
echo "  • Added should_pause_for_interactive_checkpoint() method"
echo "  • Added format_interactive_checkpoint_message() method"
echo "  • Added checkpoint logic in main execution loop"
echo "  • Added progress display and user prompt at checkpoints"
echo ""
echo "Files created:"
echo "  • INTERACTIVE_MODE.md - User documentation"
echo "  • interactive_example.py - Usage example"
echo "  • test_interactive_mode.py - Test suite"
echo "  • verify_interactive_modifications.sh - This verification script"
echo ""
echo "Next steps:"
echo "  1. Review the documentation: cat INTERACTIVE_MODE.md"
echo "  2. Test the functionality (requires dependencies): python3 interactive_example.py"
echo "  3. Integrate into your workflow"
echo ""
