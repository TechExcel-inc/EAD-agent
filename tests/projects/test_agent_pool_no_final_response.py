"""Tests for recoverable provider no-final-response handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from projects.agent_pool import (
    AgentNoFinalResponseError,
    SessionAgentPool,
    _build_user_error_message,
    _conversation_has_recoverable_progress,
    _is_no_final_response_error,
)


def test_conversation_has_recoverable_progress_from_tool_messages() -> None:
    history = [
        {"role": "user", "content": "login"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "browser_snapshot"}}]},
        {"role": "tool", "content": '{"success": true}'},
    ]
    assert _conversation_has_recoverable_progress(history) is True


def test_conversation_without_tool_progress_is_not_recoverable() -> None:
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "working on it"},
    ]
    assert _conversation_has_recoverable_progress(history) is False


def test_build_user_error_message_after_recovery_attempt() -> None:
    err = AgentNoFinalResponseError(
        "Agent run did not complete and produced no final response.",
        recovery_attempted=True,
    )
    msg = _build_user_error_message(err)
    assert "interrupted twice" in msg
    assert "continue from the last browser/tool state" in msg
    assert "⚠️ Agent execution error" not in msg


def test_build_user_error_message_for_credit_error() -> None:
    msg = _build_user_error_message(RuntimeError("402 insufficient balance for model"))
    assert "credits/quota exhausted" in msg
    assert _is_no_final_response_error(RuntimeError("did not complete and produced no final response."))


@patch.object(SessionAgentPool, "_create_agent")
@patch.object(SessionAgentPool, "_get_conversation_history")
@patch.object(SessionAgentPool, "_resolve_session_id")
def test_send_message_recovers_once_from_tool_progress(
    mock_resolve_session_id: MagicMock,
    mock_get_history: MagicMock,
    mock_create_agent: MagicMock,
) -> None:
    mock_resolve_session_id.return_value = "sess-1"
    mock_get_history.return_value = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "browser_snapshot"}}]},
        {"role": "tool", "content": '{"success": true}'},
    ]

    agent = MagicMock()
    agent.run_conversation.side_effect = [
        {"completed": False, "final_response": ""},
        {"completed": True, "final_response": "Continuing exploration."},
    ]
    mock_create_agent.return_value = agent

    pool = SessionAgentPool()
    out = pool.send_message(
        session_key="eadproj-exec-run-1",
        user_message="continue",
        session_id="sess-1",
        enable_tools=True,
    )

    assert agent.run_conversation.call_count == 2
    assert out["recovered"] is True
    assert out["result"]["final_response"] == "Continuing exploration."


@patch.object(SessionAgentPool, "_create_agent")
@patch.object(SessionAgentPool, "_get_conversation_history")
@patch.object(SessionAgentPool, "_resolve_session_id")
def test_send_message_raises_after_failed_recovery(
    mock_resolve_session_id: MagicMock,
    mock_get_history: MagicMock,
    mock_create_agent: MagicMock,
) -> None:
    mock_resolve_session_id.return_value = "sess-1"
    mock_get_history.return_value = [
        {"role": "tool", "content": '{"success": true}'},
    ]

    agent = MagicMock()
    agent.run_conversation.side_effect = [
        {"completed": False, "final_response": ""},
        {"completed": False, "final_response": ""},
    ]
    mock_create_agent.return_value = agent

    pool = SessionAgentPool()
    with pytest.raises(AgentNoFinalResponseError) as exc:
        pool.send_message(
            session_key="eadproj-exec-run-1",
            user_message="continue",
            session_id="sess-1",
            enable_tools=True,
        )

    assert exc.value.recovery_attempted is True
    assert agent.run_conversation.call_count == 2


@patch.object(SessionAgentPool, "send_message")
@patch.object(SessionAgentPool, "_resolve_session_id")
def test_send_message_async_appends_softer_message_after_failed_recovery(
    mock_resolve_session_id: MagicMock,
    mock_send_message: MagicMock,
) -> None:
    mock_resolve_session_id.return_value = "sess-1"
    mock_send_message.side_effect = AgentNoFinalResponseError(
        "Agent run did not complete and produced no final response.",
        recovery_attempted=True,
    )

    pool = SessionAgentPool()
    db = MagicMock()
    with patch.object(pool, "_get_session_db", return_value=db):
        with pytest.raises(AgentNoFinalResponseError):
            pool.send_message_async(
                session_key="eadproj-exec-run-1",
                user_message="continue",
                session_id="sess-1",
                enable_tools=True,
            )
            future = pool._running_futures.get("eadproj-exec-run-1")
            if future:
                future.result()

    db.append_message.assert_called_once()
    appended = db.append_message.call_args.kwargs["content"]
    assert "interrupted twice" in appended
