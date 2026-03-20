from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import get_settings
from app.models.schemas import JiraTicket, ProcessNotesRequest, ProcessNotesResponse
from app.services.jira_client import JiraClient
from app.services.note_parser import NoteParserService
from app.services.openai_client import OpenAIJSONClient
from app.services.task_mapper import TaskMapperService
from app.services.time_estimator import TimeEstimatorService
from app.services.worklog_orchestrator import WorklogOrchestrator

router = APIRouter(tags=["worklog"])


@lru_cache(maxsize=1)
def get_orchestrator() -> WorklogOrchestrator:
    settings = get_settings()
    openai_client = OpenAIJSONClient(settings)
    jira_client = JiraClient(settings)
    note_parser = NoteParserService(openai_client)
    task_mapper = TaskMapperService(settings, openai_client)
    time_estimator = TimeEstimatorService(openai_client)
    return WorklogOrchestrator(
        jira_client=jira_client,
        note_parser=note_parser,
        task_mapper=task_mapper,
        time_estimator=time_estimator,
    )


@router.post(
    "/process",
    response_model=ProcessNotesResponse,
    response_model_by_alias=False,
    status_code=status.HTTP_200_OK,
)
async def process_notes(
    request: ProcessNotesRequest,
    orchestrator: WorklogOrchestrator = Depends(get_orchestrator),
) -> ProcessNotesResponse:
    try:
        return await orchestrator.process(
            notes=request.notes,
            working_hours=request.working_hours,
            ticket_prefix=request.ticket_prefix,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/tickets",
    response_model=list[JiraTicket],
    response_model_by_alias=False,
    status_code=status.HTTP_200_OK,
)
async def get_tickets(
    project_key: str | None = Query(default=None, min_length=1, description="Project key prefix such as GA or ILPQC."),
    orchestrator: WorklogOrchestrator = Depends(get_orchestrator),
) -> list[JiraTicket]:
    try:
        normalized_project_key = project_key.strip().upper() if project_key else None
        return await orchestrator._jira_client.get_assigned_tickets(project_key=normalized_project_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
