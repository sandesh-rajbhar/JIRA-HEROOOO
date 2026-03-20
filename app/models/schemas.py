from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class TaskCategory(str, Enum):
    UI = "UI"
    BACKEND = "Backend"
    BUGFIX = "Bugfix"
    VALIDATION = "Validation"
    REFACTOR = "Refactor"
    MEETING = "Meeting"
    UNKNOWN = "Unknown"


class StructuredTask(BaseModel):
    title: str = Field(min_length=3)
    category: TaskCategory
    details: list[str] = Field(default_factory=list)
    is_unclear: bool = False


class JiraTicket(BaseModel):
    ticket_id: str = Field(alias="issue_key")
    summary: str
    description: str = ""

    model_config = {"populate_by_name": True}


class TaskTicketMatch(BaseModel):
    task_index: int = Field(ge=0)
    task_title: str
    ticket_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class TaskTimeAllocation(BaseModel):
    task_index: int = Field(ge=0)
    bucket_id: str
    time_hours: float = Field(ge=0.0)


class TicketWorklog(BaseModel):
    ticket_id: str
    time_hours: float = Field(ge=0.0)
    updates: list[str] = Field(default_factory=list)


class UnmappedWork(BaseModel):
    title: str
    details: list[str] = Field(default_factory=list)
    reason: str
    suggested_time_hours: float = Field(ge=0.0)


class ProcessNotesRequest(BaseModel):
    notes: str = Field(min_length=1)
    working_hours: float = Field(gt=0)

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Notes must not be empty.")
        return cleaned


class ProcessNotesResponse(BaseModel):
    tickets: list[TicketWorklog] = Field(default_factory=list)
    unmapped: list[UnmappedWork] = Field(default_factory=list)


class LLMTaskMapping(BaseModel):
    task_index: int = Field(ge=0)
    ticket_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class ParseTasksLLMResponse(BaseModel):
    tasks: list[StructuredTask]


class TaskMappingLLMResponse(BaseModel):
    mappings: list[LLMTaskMapping]


class LLMTimeAllocation(BaseModel):
    task_index: int = Field(ge=0)
    time_hours: float = Field(ge=0.0)


class TimeEstimationLLMResponse(BaseModel):
    allocations: list[LLMTimeAllocation]
