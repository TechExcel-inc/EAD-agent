"""
EAD project agent tools.

Registers read_ead_execution and report_running_step with the Hermes tool registry.
These tools allow the agent to read execution state and report milestones
during a project run.
"""

import json
import logging
from typing import Optional

from .store import ProjectStore

logger = logging.getLogger(__name__)

_store: Optional[ProjectStore] = None


def _get_store() -> ProjectStore:
    global _store
    if _store is None:
        _store = ProjectStore()
    return _store


def register_project_tools(store: Optional[ProjectStore] = None) -> None:
    global _store
    if store:
        _store = store

    try:
        from tools.registry import registry
    except ImportError:
        logger.warning("[ead_tools] Tool registry not available, skipping registration")
        return

    def _read_ead_execution(args: dict, context: dict = None) -> str:
        s = _get_store()
        execution_id = args.get("execution_id", "")
        execution = s.get_execution(execution_id)
        if not execution:
            return json.dumps({"error": f"Execution {execution_id} not found"})

        screenshots_recorded = sum(
            1 for entry in (execution.progress_log or [])
            if entry.kind == "tool_result" and entry.thumbnail_url
        )

        return json.dumps({
            "id": execution.id,
            "status": execution.status.value,
            "progress_percentage": execution.progress_percentage,
            "paused": execution.paused,
            "steps_count": len(execution.steps),
            "results_count": len(execution.results),
            "screenshots_recorded": screenshots_recorded,
            "executor_hint": execution.executor_hint,
            "cancel_reason": execution.cancel_reason,
        })

    registry.register(
        name="read_ead_execution",
        toolset="project",
        schema={
            "type": "object",
            "description": "Read the current status and results of an EAD project execution. "
                           "Use this to check progress, view step results, and see screenshots recorded.",
            "properties": {
                "execution_id": {
                    "type": "string",
                    "description": "The execution ID to read",
                },
            },
            "required": ["execution_id"],
        },
        handler=_read_ead_execution,
        description="Read EAD project execution status and results",
    )

    def _report_running_step(args: dict, context: dict = None) -> str:
        from .models import StepResult, StepArtifact, StepStatus

        s = _get_store()
        execution_id = args.get("execution_id", "")
        title = args.get("title", "")
        description = args.get("description", "")
        thumbnail_urls = args.get("thumbnail_urls", [])

        execution = s.get_execution(execution_id)
        if not execution:
            return json.dumps({"error": f"Execution {execution_id} not found"})

        step_num = len(execution.steps) + 1
        artifacts = [
            StepArtifact(
                type="screenshot",
                path=url,
                captured_at=__import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
            )
            for url in thumbnail_urls
        ]

        new_step = StepResult(
            step_id=f"step-{step_num}",
            title=title,
            status=StepStatus.COMPLETED,
            summary=description,
            artifacts=artifacts,
        )

        current_steps = list(execution.steps) + [new_step]
        s.update_execution(execution_id, steps=current_steps, current_step_id=new_step.step_id)

        logger.info("[ead_tools] Reported step %s for execution %s: %s", new_step.step_id, execution_id, title)
        return json.dumps({"recorded": True, "step_id": new_step.step_id})

    registry.register(
        name="report_running_step",
        toolset="project",
        schema={
            "type": "object",
            "description": "Report a milestone step during an EAD project execution. "
                           "Call this when you complete a significant action like navigating to a page, "
                           "filling a form, or discovering a new PFM node.",
            "properties": {
                "execution_id": {
                    "type": "string",
                    "description": "The execution ID this step belongs to",
                },
                "title": {
                    "type": "string",
                    "description": "Short title for this step (e.g. 'Navigated to login page')",
                },
                "description": {
                    "type": "string",
                    "description": "Description of what happened in this step",
                },
                "thumbnail_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Screenshot URLs captured during this step",
                },
            },
            "required": ["execution_id", "title", "description"],
        },
        handler=_report_running_step,
        description="Report a milestone step during EAD project execution",
    )

    logger.info("[ead_tools] Registered read_ead_execution and report_running_step")
