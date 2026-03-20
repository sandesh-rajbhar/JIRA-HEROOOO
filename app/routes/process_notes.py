from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import get_settings
from app.models.schemas import ProcessNotesRequest, ProcessNotesResponse
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


@router.post("/process", response_model=ProcessNotesResponse, status_code=status.HTTP_200_OK)
async def process_notes(
    request: ProcessNotesRequest,
    orchestrator: WorklogOrchestrator = Depends(get_orchestrator),
) -> ProcessNotesResponse:
    try:
        return await orchestrator.process(notes=request.notes, working_hours=request.working_hours)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
