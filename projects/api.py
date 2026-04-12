"""
Project API handlers for the Hermes API server.

Provides REST endpoints for EAD project template and execution management,
mirroring the RPC methods from EAD-EXP's gateway.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, Optional

try:
    from aiohttp import web

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    web = None

from projects.models import (
    ExecutionStatus,
    ProjectAuthMode,
    ProjectExecute,
    ProjectTemplate,
)
from projects.store import ProjectStore

logger = logging.getLogger(__name__)


def _json_response(data: Any, status: int = 200) -> "web.Response":
    return web.json_response(data, status=status)


def _to_snake_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert camelCase dict keys to snake_case for Pydantic model compatibility."""
    out: Dict[str, Any] = {}
    for k, v in data.items():
        import re

        snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", k).lower()
        if isinstance(v, dict):
            out[snake] = _to_snake_dict(v)
        elif isinstance(v, list):
            out[snake] = [_to_snake_dict(item) if isinstance(item, dict) else item for item in v]
        else:
            out[snake] = v
    return out


def _error_response(message: str, status: int = 400, code: str = "bad_request") -> "web.Response":
    return web.json_response({"error": {"message": message, "code": code}}, status=status)


def _to_camel_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert snake_case dict keys to camelCase for UI compatibility."""
    out: Dict[str, Any] = {}
    for k, v in data.items():
        components = k.split("_")
        camel = components[0] + "".join(w.capitalize() for w in components[1:])
        if isinstance(v, dict):
            out[camel] = _to_camel_dict(v)
        elif isinstance(v, list):
            out[camel] = [_to_camel_dict(item) if isinstance(item, dict) else item for item in v]
        else:
            out[camel] = v
    return out


def _template_json(template) -> "web.Response":
    """Serialize a ProjectTemplate with camelCase keys for the UI."""
    raw = json.loads(template.model_dump_json())
    return _json_response(_to_camel_dict(raw))


def _templates_json(templates) -> "web.Response":
    """Serialize a list of ProjectTemplates with camelCase keys for the UI."""
    raw_list = [json.loads(t.model_dump_json()) for t in templates]
    return _json_response(
        {"templates": [_to_camel_dict(t) for t in raw_list], "activeTemplateId": None}
    )


class ProjectHandlers:
    """Handles /v1/projects/* API endpoints."""

    def __init__(self, store: Optional[ProjectStore] = None, executor=None):
        self._store = store or ProjectStore()
        self._executor = executor

    # ------------------------------------------------------------------
    # Template endpoints
    # ------------------------------------------------------------------

    async def handle_list_templates(self, request: "web.Request") -> "web.Response":
        templates = self._store.list_templates()
        active_id = self._store.get_active_template_id()
        raw_list = [json.loads(t.model_dump_json()) for t in templates]
        return _json_response(
            {
                "templates": [_to_camel_dict(t) for t in raw_list],
                "activeTemplateId": active_id,
            }
        )

    async def handle_get_template(self, request: "web.Request") -> "web.Response":
        template_id = request.match_info["template_id"]
        template = self._store.get_template(template_id)
        if not template:
            return _error_response(f"Template {template_id} not found", 404, "not_found")
        return _template_json(template)

    async def handle_create_template(self, request: "web.Request") -> "web.Response":
        try:
            body = _to_snake_dict(await request.json())
        except Exception:
            return _error_response("Invalid JSON")

        try:
            template = ProjectTemplate(**body)
        except Exception as e:
            return _error_response(f"Invalid template data: {e}")

        created = self._store.create_template(template)
        return _template_json(created)

    async def handle_update_template(self, request: "web.Request") -> "web.Response":
        template_id = request.match_info["template_id"]
        try:
            body = _to_snake_dict(await request.json())
        except Exception:
            return _error_response("Invalid JSON")

        updated = self._store.update_template(template_id, **body)
        if not updated:
            return _error_response(f"Template {template_id} not found", 404, "not_found")
        return _template_json(updated)

    async def handle_delete_template(self, request: "web.Request") -> "web.Response":
        template_id = request.match_info["template_id"]
        deleted = self._store.delete_template(template_id)
        if not deleted:
            return _error_response(f"Template {template_id} not found", 404, "not_found")
        return _json_response({"deleted": True})

    async def handle_activate_template(self, request: "web.Request") -> "web.Response":
        template_id = request.match_info["template_id"]
        template = self._store.get_template(template_id)
        if not template:
            return _error_response(f"Template {template_id} not found", 404, "not_found")
        self._store.set_active_template_id(template_id)
        return _json_response({"active_template_id": template_id})

    # ------------------------------------------------------------------
    # Execution endpoints
    # ------------------------------------------------------------------

    async def handle_list_executions(self, request: "web.Request") -> "web.Response":
        template_id = request.query.get("template_id")
        status = request.query.get("status")
        executions = self._store.list_executions(
            template_id=template_id or None,
            status=status or None,
        )
        return _json_response(
            {
                "executions": [_to_camel_dict(json.loads(e.model_dump_json())) for e in executions],
            }
        )

    async def handle_get_execution(self, request: "web.Request") -> "web.Response":
        execution_id = request.match_info["execution_id"]
        execution = self._store.get_execution(execution_id)
        if not execution:
            return _error_response(f"Execution {execution_id} not found", 404, "not_found")
        raw = json.loads(execution.model_dump_json())
        return _json_response(_to_camel_dict(raw))

    async def handle_run_execution(self, request: "web.Request") -> "web.Response":
        try:
            body = await request.json()
        except Exception:
            return _error_response("Invalid JSON")

        body = _to_snake_dict(body)

        template_id = body.get("template_id") or body.get("templateId")
        if not template_id:
            return _error_response("template_id is required")

        template = self._store.get_template(template_id)
        if not template:
            return _error_response(f"Template {template_id} not found", 404, "not_found")

        execution = ProjectExecute(
            linked_template_id=template.id,
            name=body.get("name", f"Run - {template.name}"),
            description=body.get("description", template.description),
            target_url=body.get("target_url", template.target_url),
            ai_prompt=body.get("ai_prompt", template.ai_prompt),
            auth_mode=template.auth_mode,
            auth_login_url=template.auth_login_url,
            auth_session_profile=template.auth_session_profile,
            auth_instructions=template.auth_instructions,
            time_budget_minutes=body.get("time_budget_minutes", template.time_budget_minutes),
            cost_budget_dollars=body.get("cost_budget_dollars", template.cost_budget_dollars),
            show_local_browser=body.get("show_local_browser", False),
            status=ExecutionStatus.PENDING,
            start_time=int(time.time() * 1000),
        )

        created = self._store.create_execution(execution)
        logger.info("[projects] Created execution %s for template %s", execution.id, template.id)

        session_key = f"eadproj-exec-{created.id}"
        try:
            from hermes_state import SessionDB

            db = SessionDB()
            session_id = f"eadproj-{uuid.uuid4().hex[:12]}"
            db.create_session(session_id=session_id, source="api_server", system_prompt="")
            db.set_session_title(session_id, session_key)

            ai_prompt = created.ai_prompt or template.ai_prompt or ""
            target_url = created.target_url or template.target_url or ""
            bootstrap_msg = f"Task: {ai_prompt}"
            if target_url:
                bootstrap_msg += f"\n\nTarget URL: {target_url}"

            db.append_message(session_id=session_id, role="user", content=bootstrap_msg)
            logger.info(
                "[projects] Bootstrapped session %s for execution %s", session_id, created.id
            )

            self._store.update_execution(created.id, run_session_key=session_key)
        except Exception as e:
            logger.warning(
                "[projects] Session bootstrap failed for execution %s: %s", created.id, e
            )

        if self._executor:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._executor.start_execution(created.id))
                logger.info("[projects] Executor started for execution %s", created.id)
            except Exception as e:
                logger.error("[projects] Failed to start executor for %s: %s", created.id, e)

        raw = json.loads(created.model_dump_json())
        return _json_response(_to_camel_dict(raw), status=201)

    async def handle_cancel_execution(self, request: "web.Request") -> "web.Response":
        execution_id = request.match_info["execution_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}

        execution = self._store.get_execution(execution_id)
        if not execution:
            return _error_response(f"Execution {execution_id} not found", 404, "not_found")

        stop_kind = body.get("stop_kind", "cancel")
        cancel_reason = body.get("reason", "")

        final_status = (
            ExecutionStatus.COMPLETED if stop_kind == "finish" else ExecutionStatus.CANCELLED
        )
        updated = self._store.update_execution(
            execution_id,
            status=final_status,
            paused=False,
            operator_stop_kind=stop_kind,
            cancel_reason=cancel_reason,
            duration_ms=int(time.time() * 1000) - (execution.start_time or int(time.time() * 1000)),
        )

        if self._executor:
            if stop_kind == "finish":
                self._executor._cancelled.add(execution_id)
            await self._executor.cancel_execution(execution_id)

        logger.info("[projects] Cancelled execution %s (kind=%s)", execution_id, stop_kind)
        raw = json.loads(updated.model_dump_json())
        return _json_response(_to_camel_dict(raw))

    async def handle_pause_execution(self, request: "web.Request") -> "web.Response":
        execution_id = request.match_info["execution_id"]
        execution = self._store.get_execution(execution_id)
        if not execution:
            return _error_response(f"Execution {execution_id} not found", 404, "not_found")

        if execution.status != ExecutionStatus.RUNNING:
            return _error_response(f"Cannot pause execution in status {execution.status.value}")

        updated = self._store.update_execution(execution_id, paused=True)
        logger.info("[projects] Paused execution %s", execution_id)
        raw = json.loads(updated.model_dump_json())
        return _json_response(_to_camel_dict(raw))

    async def handle_resume_execution(self, request: "web.Request") -> "web.Response":
        execution_id = request.match_info["execution_id"]
        execution = self._store.get_execution(execution_id)
        if not execution:
            return _error_response(f"Execution {execution_id} not found", 404, "not_found")

        if not execution.paused:
            return _error_response("Execution is not paused")

        updated = self._store.update_execution(execution_id, paused=False)
        logger.info("[projects] Resumed execution %s", execution_id)
        raw = json.loads(updated.model_dump_json())
        return _json_response(_to_camel_dict(raw))

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def register_routes(self, app: "web.Application") -> None:
        app.router.add_get("/v1/projects/templates", self.handle_list_templates)
        app.router.add_get("/v1/projects/templates/{template_id}", self.handle_get_template)
        app.router.add_post("/v1/projects/templates", self.handle_create_template)
        app.router.add_patch("/v1/projects/templates/{template_id}", self.handle_update_template)
        app.router.add_delete("/v1/projects/templates/{template_id}", self.handle_delete_template)
        app.router.add_post(
            "/v1/projects/templates/{template_id}/activate", self.handle_activate_template
        )

        app.router.add_get("/v1/projects/executions", self.handle_list_executions)
        app.router.add_get("/v1/projects/executions/{execution_id}", self.handle_get_execution)
        app.router.add_post("/v1/projects/executions/run", self.handle_run_execution)
        app.router.add_post(
            "/v1/projects/executions/{execution_id}/cancel", self.handle_cancel_execution
        )
        app.router.add_post(
            "/v1/projects/executions/{execution_id}/pause", self.handle_pause_execution
        )
        app.router.add_post(
            "/v1/projects/executions/{execution_id}/resume", self.handle_resume_execution
        )
