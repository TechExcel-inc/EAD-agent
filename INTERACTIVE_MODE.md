# Interactive Mode for EAD-Agent

## Overview

The interactive mode feature makes the AI agent more collaborative by periodically pausing execution to summarize progress and wait for your confirmation before proceeding. This is particularly useful for:

- **Complex tasks** where you want to review progress periodically
- **Exploratory work** where direction may change based on findings
- **Learning** how the agent approaches problems
- **Safety** when you want to ensure the agent stays on track

## How It Works

When interactive mode is enabled, the agent:

1. **Executes normally** using available tools and reasoning
2. **Tracks iterations** counting each tool-calling cycle
3. **Pauses at checkpoints** (every N iterations, default: 5)
4. **Shows progress summary** including:
   - Current iteration count
   - Recent tool usage and actions
   - Current status
5. **Waits for your input** to decide next steps:
   - `continue` - resume execution
   - `stop` - end the session
   - New instructions - change direction

## Configuration

### Enable Interactive Mode

```python
from run_agent import AIAgent

agent = AIAgent(
    model="claude-opus-4-6",
    interactive_mode=True,    # Enable interactive mode
    summary_interval=5,       # Pause every 5 iterations
    max_iterations=90,        # Maximum iterations
)
```

### Parameters

- **`interactive_mode`** (bool, default: `False`)
  - Enable/disable interactive checkpoint mode

- **`summary_interval`** (int, default: `5`)
  - Number of iterations between checkpoints
  - Recommended values: 3-10 depending on task complexity
  - Lower values = more frequent check-ins, more control
  - Higher values = fewer interruptions, more autonomy

## Example Usage

### Basic Example

```python
from run_agent import AIAgent

# Create agent with interactive mode
agent = AIAgent(
    model="claude-opus-4-6",
    interactive_mode=True,
    summary_interval=5,
)

# Run a complex task
result = agent.run_conversation(
    user_message="Analyze this codebase and identify security vulnerabilities"
)
```

### With Custom Interval

```python
# For longer, more autonomous tasks
agent = AIAgent(
    model="claude-opus-4-6",
    interactive_mode=True,
    summary_interval=10,  # Check every 10 iterations
    max_iterations=100,
)
```

### Programmatic Resume

When the agent pauses at a checkpoint, the `run_conversation()` method returns with:
- `interrupted: True`
- Exit reason: `"interactive_checkpoint"`

You can then resume by calling `run_conversation()` again with the same conversation history:

```python
agent = AIAgent(
    model="claude-opus-4-6",
    interactive_mode=True,
    summary_interval=5,
)

# First run - will pause at checkpoint
result1 = agent.run_conversation(
    user_message="Explore this codebase"
)

while result1.get("interrupted"):
    # Agent paused at checkpoint
    user_input = input("Continue or new instructions? ")

    if user_input.lower() == "continue":
        # Resume with same context
        result1 = agent.run_conversation(
            user_message="continue",
            conversation_history=result1["messages"],
        )
    elif user_input.lower() == "stop":
        break
    else:
        # Change direction
        result1 = agent.run_conversation(
            user_message=user_input,
            conversation_history=result1["messages"],
        )
```

## Output Example

When the agent reaches a checkpoint, you'll see output like:

```
📊 **Progress Checkpoint (Iteration 5)**
   Completed 5 iterations so far.
   Reviewing progress and pausing for your input...

🔧 **Recent Actions:**
   • browser
   • read_file
   • write_file
   • exec

⏸️  **Agent Paused - Awaiting Your Direction**
   Options:
   • Type 'continue' to resume execution
   • Type 'stop' to end this session
   • Provide new instructions to change direction
```

## Best Practices

### 1. Choose the Right Interval

- **3-5 iterations**: High-touch tasks, learning, critical safety
- **5-10 iterations**: Standard exploration, development tasks
- **10+ iterations**: Long-running tasks with periodic review

### 2. Clear Communication

When resuming with new instructions:
- Be specific about what to change
- Reference what the agent has found so far
- Confirm if the agent should continue or start fresh

### 3. Task Complexity

For very simple tasks, interactive mode may add unnecessary overhead. Consider:
- Task complexity
- Time constraints
- Need for oversight

### 4. Error Recovery

If the agent encounters errors:
- The checkpoint provides natural recovery points
- You can redirect before issues compound
- Fewer iterations are lost when problems occur

## Comparison with Standard Mode

| Feature | Standard Mode | Interactive Mode |
|---------|--------------|------------------|
| Autonomy | High | Medium |
| Oversight | Low | High |
| Interruptions | Only on errors | Periodic checkpoints |
| Control | End-task only | Continuous steering |
| Use Case | Batch processing | Collaborative work |

## Technical Details

### Implementation

- Checkpoints are checked after each iteration completes
- Recent tool usage (last 5 tools) is displayed for context
- The interrupt flag is set to break the execution loop
- Conversation history is preserved for resuming

### Performance Impact

- Minimal overhead: only a modulo check and display logic
- No additional API calls for summaries
- Resuming uses existing conversation context

### Thread Safety

- The interrupt mechanism is thread-safe
- Multiple concurrent agents can use interactive mode independently

## Troubleshooting

### Agent Not Pausing

- Verify `interactive_mode=True`
- Check `summary_interval` is set appropriately
- Ensure `max_iterations` allows for at least one checkpoint

### Resume Not Working

- Always pass `conversation_history` when resuming
- Clear interrupt state with `agent.clear_interrupt()`
- Use the same agent instance for continuation

### Too Many Interruptions

- Increase `summary_interval` to 10 or 15
- Consider disabling interactive mode for well-understood tasks
- Use batch processing for repetitive tasks

## Future Enhancements

Potential improvements being considered:

- **Configurable summary detail**: Brief vs. detailed summaries
- **Automatic continuation**: Skip checkpoint if making good progress
- **Smart intervals**: Adjust based on task complexity
- **Progress visualization**: Charts and graphs of agent activity

## See Also

- `run_agent.py` - Main agent implementation
- `interactive_example.py` - Working example script
- EAD-FM documentation - Feature mapping methodology
