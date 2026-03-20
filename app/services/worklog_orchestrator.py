from __future__ import annotations

from collections import defaultdict
import re

from app.models.schemas import (
    ProcessNotesResponse,
    StructuredTask,
    TaskTicketMatch,
    TaskTimeAllocation,
    TicketWorklog,
    UnmappedWork,
)
from app.services.jira_client import JiraClient
from app.services.note_parser import NoteParserService
from app.services.task_mapper import TaskMapperService
from app.services.time_estimator import TimeEstimatorService


class WorklogOrchestrator:
    def __init__(
        self,
        jira_client: JiraClient,
        note_parser: NoteParserService,
        task_mapper: TaskMapperService,
        time_estimator: TimeEstimatorService,
    ) -> None:
        self._jira_client = jira_client
        self._note_parser = note_parser
        self._task_mapper = task_mapper
        self._time_estimator = time_estimator

    async def process(
        self,
        notes: str,
        working_hours: float,
        ticket_prefix: str | None = None,
    ) -> ProcessNotesResponse:
        tasks = await self._note_parser.parse_notes(notes)
        tickets = await self._jira_client.get_assigned_tickets(project_key=ticket_prefix)
        mappings = await self._task_mapper.map_tasks(tasks, tickets)
        allocations = await self._time_estimator.estimate(tasks, mappings, working_hours)
        return self._build_response(tasks, mappings, allocations)

    def _build_response(
        self,
        tasks: list[StructuredTask],
        mappings: list[TaskTicketMatch],
        allocations: list[TaskTimeAllocation],
    ) -> ProcessNotesResponse:
        allocation_lookup = {allocation.task_index: allocation for allocation in allocations}
        ticket_times: defaultdict[str, float] = defaultdict(float)
        ticket_updates: defaultdict[str, list[str]] = defaultdict(list)
        unmapped: list[UnmappedWork] = []

        for index, task in enumerate(tasks):
            mapping = mappings[index]
            allocation = allocation_lookup[index]
            task_updates = self._task_updates(task)

            if mapping.ticket_id == "UNMAPPED":
                unmapped.append(
                    UnmappedWork(
                        title=task.title,
                        details=task.details,
                        reason=self._unmapped_reason(task, mapping),
                        suggested_time_hours=allocation.time_hours,
                    )
                )
                continue

            ticket_times[mapping.ticket_id] += allocation.time_hours
            for update in task_updates:
                if update not in ticket_updates[mapping.ticket_id]:
                    ticket_updates[mapping.ticket_id].append(update)

        tickets = [
            TicketWorklog(
                ticket_id=ticket_id,
                time_hours=round(ticket_times[ticket_id], 2),
                updates=ticket_updates[ticket_id],
            )
            for ticket_id in sorted(ticket_times.keys())
        ]
        return ProcessNotesResponse(tickets=tickets, unmapped=unmapped)

    def _task_updates(self, task: StructuredTask) -> list[str]:
        updates: list[str] = [self._ensure_period(task.title)]
        seen_keys = {self._canonical_update_key(task.title)}
        for detail in task.details:
            detail_text = self._ensure_period(detail)
            detail_key = self._canonical_update_key(detail_text)
            if detail_key and detail_key not in seen_keys:
                updates.append(detail_text)
                seen_keys.add(detail_key)
        return updates

    def _unmapped_reason(self, task: StructuredTask, mapping: TaskTicketMatch) -> str:
        if task.category.value == "Meeting":
            return "Meeting work is tracked separately from Jira tickets."
        if task.is_unclear:
            return "Task details were too vague to map safely."
        return mapping.reasoning

    def _ensure_period(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            return cleaned
        if cleaned[-1] in {".", "!", "?"}:
            return cleaned
        return f"{cleaned}."

    def _canonical_update_key(self, value: str) -> str:
        normalized = value.lower().strip()
        normalized = re.sub(
            r"^(investigated|fixed|added|updated|implemented|handled|handling|worked on|working on)\s+",
            "",
            normalized,
        )
        normalized = re.sub(r"[.!?]+$", "", normalized)
        return normalized.strip()
