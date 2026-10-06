"""FastAPI entry point for the automation control application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.config import settings
from app.intervention.human_capture import HumanActionCapture
from app.intervention.manager import InterventionManager
from app.models.runs import (
    CreateRunRequest,
    CreateRunResponse,
    MemberSavingsWorkflowRequest,
    RunStatusResponse,
    WorkflowMode,
)
from app.runs.manager import RunManager
from app.runs.session import ControlOwner, RunStatus
from app.workflows.member_savings import MemberSavingsWorkflowService

run_manager = RunManager()
human_action_capture = HumanActionCapture()
intervention_manager = InterventionManager()
workflow_service = MemberSavingsWorkflowService(run_manager)
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Clean up unfinished background tasks during application shutdown."""
    yield
    await run_manager.shutdown()


app = FastAPI(title="Computer-Use Automation Control", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the evaluator-facing workflow launcher."""
    sessions = list(run_manager.sessions.values())
    sessions.reverse()
    return templates.TemplateResponse(
        request=request,
        name="workflow_home.html",
        context={
            "openai_configured": settings.openai_api_key is not None,
            "sessions": sessions,
            "error": None,
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "control"}


@app.post("/api/workflows/member-savings", response_model=CreateRunResponse)
async def create_member_savings_workflow(
    request: MemberSavingsWorkflowRequest,
) -> CreateRunResponse:
    """Start the complete assignment workflow through the JSON API."""
    if request.mode is WorkflowMode.OPENAI and settings.openai_api_key is None:
        raise HTTPException(
            status_code=400, detail="OPENAI_API_KEY is not configured; choose mode='mock'."
        )
    session = workflow_service.start(request)
    return CreateRunResponse(run_id=session.run_id, status=session.status)


@app.post("/workflows/member-savings", response_class=HTMLResponse)
async def start_member_savings_from_ui(
    request: Request,
    mode: str = Form(...),
    goal: str = Form(...),
    target_url: str = Form(...),
    discovery_member_id: str = Form(...),
    replay_member_id: str = Form(...),
):
    """Validate the launcher form and redirect to live run status."""
    try:
        workflow_request = MemberSavingsWorkflowRequest(
            mode=mode,
            goal=goal,
            target_url=target_url,
            discovery_member_id=discovery_member_id,
            replay_member_id=replay_member_id,
        )
        if workflow_request.mode is WorkflowMode.OPENAI and settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is not configured. Choose credential-free mock mode.")
    except (ValidationError, ValueError) as error:
        sessions = list(run_manager.sessions.values())
        sessions.reverse()
        return templates.TemplateResponse(
            request=request,
            name="workflow_home.html",
            context={
                "openai_configured": settings.openai_api_key is not None,
                "sessions": sessions,
                "error": str(error),
            },
            status_code=422,
        )

    session = workflow_service.start(workflow_request)
    return RedirectResponse(url=f"/runs/{session.run_id}/view", status_code=303)


@app.post("/runs/demo", response_model=CreateRunResponse, deprecated=True)
async def create_demo_run(request: CreateRunRequest) -> CreateRunResponse:
    """Start the real credential-free pipeline for older API clients."""
    workflow_request = MemberSavingsWorkflowRequest(
        mode=WorkflowMode.MOCK, discovery_member_id="12345", replay_member_id="67890"
    )
    session = workflow_service.start(workflow_request)
    session.goal = request.goal
    return CreateRunResponse(run_id=session.run_id, status=session.status)


@app.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run(run_id: str) -> RunStatusResponse:
    session = run_manager.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunStatusResponse(
        run_id=session.run_id,
        goal=session.goal,
        run_type=session.run_type,
        status=session.status,
        stage=session.stage,
        stage_detail=session.stage_detail,
        stage_history=session.stage_history,
        error=session.error,
        result=session.result,
    )


@app.get("/runs/{run_id}/view", response_class=HTMLResponse)
async def run_status_page(request: Request, run_id: str):
    """Render current stage, final output, or intervention link."""
    session = run_manager.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return templates.TemplateResponse(
        request=request, name="workflow_run.html", context={"session": session}
    )


@app.get("/operator/runs/{run_id}", response_class=HTMLResponse)
async def operator_run(request: Request, run_id: str):
    """Show the current intervention for one paused run."""
    session = run_manager.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if session.current_intervention is None:
        raise HTTPException(status_code=404, detail="No active intervention")

    return templates.TemplateResponse(
        request=request,
        name="operator_run.html",
        context={
            "session": session,
            "intervention": session.current_intervention,
            "error": request.query_params.get("error"),
        },
    )


@app.post("/operator/runs/{run_id}/take-control")
async def take_control(run_id: str):
    """Give the operator control without replacing the live surface."""
    session = run_manager.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if session.current_intervention is None:
        raise HTTPException(status_code=409, detail="No active intervention")
    if session.surface is None:
        raise HTTPException(status_code=409, detail="No live surface")

    session.control_event.clear()
    session.control_owner = ControlOwner.HUMAN
    session.status = RunStatus.PAUSED
    await human_action_capture.install(session)

    return RedirectResponse(url=f"/operator/runs/{run_id}", status_code=303)


@app.post("/operator/runs/{run_id}/resume")
async def resume_automation(run_id: str):
    """Return control to the paused automation task."""
    session = run_manager.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if session.current_intervention is None:
        raise HTTPException(status_code=409, detail="No active intervention")
    if session.control_owner is not ControlOwner.HUMAN:
        return RedirectResponse(
            url=f"/operator/runs/{run_id}?error=take-control-first", status_code=303
        )

    session.control_owner = ControlOwner.RESUMING
    session.status = RunStatus.RUNNING
    session.stage_detail = "Human work submitted; automation is checking the same live page."
    session.stage_history.append(f"{session.stage}: {session.stage_detail}")
    session.control_event.set()

    return RedirectResponse(url=f"/runs/{run_id}/view", status_code=303)


@app.post("/operator/runs/{run_id}/abort")
async def abort_run(run_id: str):
    """Abort a paused run without executing its blocked action."""
    session = run_manager.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if session.current_intervention is None:
        raise HTTPException(status_code=409, detail="No active intervention")

    intervention_manager.abort(session)
    await run_manager.release_terminal_surface(session)
    return RedirectResponse(url="/", status_code=303)
