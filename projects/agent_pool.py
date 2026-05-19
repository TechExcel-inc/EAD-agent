"""
Session-bound agent pool for project chat.

Maintains AIAgent instances keyed by session_key so they can be:
- Sent new messages (auto-continue, resume)
- Interrupted by session key (abort)
- Polled for active status

Design: stateless with session persistence (Option B from the migration plan).
Each call creates a fresh AIAgent with the same session_id so it loads
its transcript from SessionDB. This avoids memory leaks from long-lived agents.
"""

import asyncio
import concurrent.futures
import logging
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_NO_FINAL_RESPONSE_ERR = "Agent run did not complete and produced no final response."
_CONTINUATION_USER_MESSAGE = (
    "Continue from the last successful browser/tool state. "
    "If login succeeded, call report_running_step with login_phase_status=success "
    "before further exploration."
)


class AgentNoFinalResponseError(RuntimeError):
    """Provider stream ended without a final assistant message."""

    def __init__(self, message: str, *, recovery_attempted: bool = False):
        super().__init__(message)
        self.recovery_attempted = recovery_attempted


def _coerce_message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _dedupe_prefetched_user_turn(
    conversation_history: List[Dict[str, Any]], user_message: str
) -> List[Dict[str, Any]]:
    """If chat.send used deliver=False then deliver=True, the DB ends with a duplicate
    user row before run_conversation appends the same turn again. Drop the trailing
    user message when it exactly matches this user_message."""
    if not conversation_history or not (user_message or "").strip():
        return conversation_history
    last = conversation_history[-1]
    if last.get("role") != "user":
        return conversation_history
    prev = _coerce_message_text(last.get("content")).strip()
    if prev == (user_message or "").strip():
        return conversation_history[:-1]
    return conversation_history


def _is_project_session(session_key: str) -> bool:
    return str(session_key or "").strip().startswith("eadproj-exec-")


def _is_no_final_response_error(err: BaseException | str) -> bool:
    lowered = str(err).strip().lower()
    return "did not complete and produced no final response" in lowered


def _conversation_has_recoverable_progress(history: List[Dict[str, Any]]) -> bool:
    """True when the transcript shows recent tool/browser work worth continuing."""
    for msg in reversed(history[-24:]):
        role = str(msg.get("role") or "").strip().lower()
        if role == "tool":
            return True
        if role == "assistant" and msg.get("tool_calls"):
            return True
    return False


def _extract_run_outcome(result: Any) -> Tuple[str, bool, str]:
    if not isinstance(result, dict):
        return "", False, ""
    final_response = str(result.get("final_response") or "").strip()
    completed = bool(result.get("completed"))
    err = str(result.get("error") or "").strip()
    return final_response, completed, err


def _is_truncation_error(err: str) -> bool:
    lower_err = err.lower()
    return "truncated due to output length limit" in lower_err or (
        "truncated" in lower_err and "output length" in lower_err
    )


def _usage_from_agent(agent: Any) -> Dict[str, int]:
    return {
        "input_tokens": getattr(agent, "session_prompt_tokens", 0) or 0,
        "output_tokens": getattr(agent, "session_completion_tokens", 0) or 0,
        "total_tokens": getattr(agent, "session_total_tokens", 0) or 0,
    }


def _build_user_error_message(err: BaseException) -> str:
    raw_err = str(err).strip()
    lowered = raw_err.lower()
    is_credit_error = (
        "402" in lowered
        or "insufficient balance" in lowered
        or "quota" in lowered
        or "credit" in lowered
    )
    if is_credit_error:
        return (
            "⚠️ Agent execution error: model/provider call failed.\n"
            f"Details: {raw_err[:260]}\n"
            "Likely cause: provider credits/quota exhausted. "
            "Please verify balance/quota and model access."
        )
    if _is_no_final_response_error(err):
        recovery_attempted = isinstance(err, AgentNoFinalResponseError) and err.recovery_attempted
        if recovery_attempted:
            return (
                "The provider stream was interrupted twice while the agent was working. "
                "The gateway already asked it to continue from the last browser/tool state. "
                "Please retry the run or switch provider/model if this keeps happening."
            )
        return (
            "⚠️ Agent execution error: provider returned no final response.\n"
            f"Details: {raw_err[:260]}\n"
            "Likely cause: transient provider timeout/stream interruption. "
            "Please retry the run or switch provider/model."
        )
    return (
        "⚠️ Agent execution error: model/provider call failed.\n"
        f"Details: {raw_err[:260]}\n"
        "Please retry. If this persists, verify provider endpoint/model configuration."
    )


class SessionAgentPool:
    """Manages agent execution per session key.

    Thread-safe: agent creation and execution happen via thread executor.
    """

    def __init__(self, adapter=None):
        self._adapter = adapter
        self._running_agents: Dict[str, Any] = {}
        self._running_futures: Dict[str, Future] = {}
        self._lock = threading.Lock()

    def _get_session_db(self):
        try:
            from hermes_state import SessionDB

            return SessionDB()
        except Exception as e:
            logger.error("[agent_pool] SessionDB unavailable: %s", e)
            return None

    def _create_agent(
        self,
        session_id: Optional[str] = None,
        ephemeral_system_prompt: Optional[str] = None,
        stream_delta_callback: Optional[Callable] = None,
        tool_progress_callback: Optional[Callable] = None,
        enabled_toolsets: Optional[List[str]] = None,
    ):
        if self._adapter is not None and hasattr(self._adapter, "_create_agent"):
            return self._adapter._create_agent(
                ephemeral_system_prompt=ephemeral_system_prompt,
                session_id=session_id,
                stream_delta_callback=stream_delta_callback,
                tool_progress_callback=tool_progress_callback,
                enabled_toolsets=enabled_toolsets,
            )

        from run_agent import AIAgent

        return AIAgent(
            session_id=session_id,
            ephemeral_system_prompt=ephemeral_system_prompt,
            stream_delta_callback=stream_delta_callback,
            tool_progress_callback=tool_progress_callback,
            enabled_toolsets=enabled_toolsets,
        )

    def _get_conversation_history(self, session_id: str) -> List[Dict[str, Any]]:
        db = self._get_session_db()
        if not db:
            return []
        try:
            return db.get_messages_as_conversation(session_id)
        except Exception as e:
            logger.warning("[agent_pool] Failed to load conversation history: %s", e)
            return []

    def _resolve_session_id(self, session_key: str) -> Optional[str]:
        db = self._get_session_db()
        if not db:
            return None
        try:
            session = db.get_session_by_title(session_key)
            if session:
                return session.get("id")
        except Exception:
            pass
        return None

    def _append_assistant_notice(self, session_id: str, content: str) -> None:
        db = self._get_session_db()
        if not db or not session_id or not content:
            return
        db.append_message(session_id=session_id, role="assistant", content=content)

    def _result_from_outcome(
        self,
        result: Any,
        agent: Any,
        *,
        recovered: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"result": result, "usage": _usage_from_agent(agent)}
        if recovered:
            payload["recovered"] = True
        return payload

    def _handle_provider_error(
        self,
        session_key: str,
        err: str,
        result: Any,
        agent: Any,
    ) -> Optional[Dict[str, Any]]:
        if _is_truncation_error(err):
            logger.warning(
                "[agent_pool] Session %s hit output truncation; deferring recovery to next turn",
                session_key,
            )
            return self._result_from_outcome(result, agent)
        raise RuntimeError(err)

    def _try_recover_no_final_response(
        self,
        session_key: str,
        session_id: Optional[str],
        agent: Any,
        conversation_history: List[Dict[str, Any]],
        *,
        enable_tools: bool,
    ) -> Optional[Dict[str, Any]]:
        if not enable_tools or not _is_project_session(session_key):
            return None
        if not _conversation_has_recoverable_progress(conversation_history):
            return None

        retry_history = conversation_history
        if session_id:
            retry_history = self._get_conversation_history(session_id)
        retry_history = _dedupe_prefetched_user_turn(retry_history, _CONTINUATION_USER_MESSAGE)

        logger.warning(
            "[agent_pool] Recoverable provider interruption for %s; continuing once from last tool state",
            session_key,
        )
        retry_result = agent.run_conversation(
            user_message=_CONTINUATION_USER_MESSAGE,
            conversation_history=retry_history,
            task_id=f"eadproj:{session_key}",
        )
        final_response, completed, err = _extract_run_outcome(retry_result)
        if final_response or completed:
            return self._result_from_outcome(retry_result, agent, recovered=True)
        if err:
            return self._handle_provider_error(session_key, err, retry_result, agent)
        return None

    def send_message(
        self,
        session_key: str,
        user_message: str,
        session_id: Optional[str] = None,
        ephemeral_system_prompt: Optional[str] = None,
        enable_tools: bool = False,
    ) -> Dict[str, Any]:
        """Send a message to the session's agent synchronously. Blocks until complete."""
        if not session_id:
            session_id = self._resolve_session_id(session_key)

        conversation_history = []
        if session_id:
            conversation_history = self._get_conversation_history(session_id)
        conversation_history = _dedupe_prefetched_user_turn(conversation_history, user_message)

        tool_sets = ["project"] if enable_tools else []
        agent = self._create_agent(
            session_id=session_id,
            ephemeral_system_prompt=ephemeral_system_prompt,
            enabled_toolsets=tool_sets,
        )

        with self._lock:
            self._running_agents[session_key] = agent

        try:
            result = agent.run_conversation(
                user_message=user_message,
                conversation_history=conversation_history,
                task_id=f"eadproj:{session_key}",
            )
            final_response, completed, err = _extract_run_outcome(result)
            if err:
                return self._handle_provider_error(session_key, err, result, agent)
            if not final_response and not completed:
                recovered = self._try_recover_no_final_response(
                    session_key,
                    session_id,
                    agent,
                    conversation_history,
                    enable_tools=enable_tools,
                )
                if recovered:
                    return recovered
                recovery_attempted = _conversation_has_recoverable_progress(conversation_history)
                raise AgentNoFinalResponseError(
                    _NO_FINAL_RESPONSE_ERR,
                    recovery_attempted=recovery_attempted,
                )
            return self._result_from_outcome(result, agent)
        finally:
            with self._lock:
                self._running_agents.pop(session_key, None)

    def send_message_async(
        self,
        session_key: str,
        user_message: str,
        session_id: Optional[str] = None,
        ephemeral_system_prompt: Optional[str] = None,
        enable_tools: bool = False,
    ) -> str:
        """Send a message asynchronously. Returns a run_id for tracking."""
        run_id = f"eadrun_{uuid.uuid4().hex[:12]}"

        def _run():
            try:
                result = self.send_message(
                    session_key=session_key,
                    user_message=user_message,
                    session_id=session_id,
                    ephemeral_system_prompt=ephemeral_system_prompt,
                    enable_tools=enable_tools,
                )
                logger.info(
                    "[agent_pool] Async run %s completed for session %s", run_id, session_key
                )
                return result
            except Exception as e:
                try:
                    sid = session_id or self._resolve_session_id(session_key)
                    if sid:
                        self._append_assistant_notice(sid, _build_user_error_message(e))
                except Exception:
                    logger.warning(
                        "[agent_pool] Failed to append user-facing error message for session %s",
                        session_key,
                    )
                logger.error(
                    "[agent_pool] Async run %s failed for session %s: %s",
                    run_id,
                    session_key,
                    e,
                    exc_info=True,
                )
                raise

        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if loop:
            future = loop.run_in_executor(None, _run)
        else:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_run)

        if future:
            with self._lock:
                self._running_futures[session_key] = future

        logger.info("[agent_pool] Started async run %s for session %s", run_id, session_key)
        return run_id

    def interrupt_agent(self, session_key: str) -> bool:
        """Interrupt the running agent for a session. Returns True if agent was active."""
        with self._lock:
            agent = self._running_agents.get(session_key)

        if agent and hasattr(agent, "interrupt"):
            agent.interrupt("Project run aborted")
            logger.info("[agent_pool] Interrupted agent for session %s", session_key)
            return True

        return False

    def is_agent_active(self, session_key: str) -> bool:
        """Check if a session has an actively running agent."""
        with self._lock:
            return session_key in self._running_agents

    def cleanup_session(self, session_key: str) -> None:
        """Remove agent and resources for a session."""
        with self._lock:
            self._running_agents.pop(session_key, None)
            future = self._running_futures.pop(session_key, None)

        if future and not future.done():
            try:
                future.cancel()
            except Exception:
                pass
