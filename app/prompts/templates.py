from __future__ import annotations

import json

from app.models.schemas import JiraTicket, StructuredTask, TaskTicketMatch


def notes_to_tasks_prompt(notes: str) -> str:
    return f"""
Convert the developer's raw daily notes into structured engineering tasks.

Rules:
- Return strict JSON only.
- Output a top-level object with a single key: "tasks".
- Each task must follow: {{"title": string, "category": "UI|Backend|Bugfix|Validation|Refactor|Meeting|Unknown", "details": string[], "is_unclear": boolean}}.
- Combine related notes into one task.
- Remove chatter, filler, greetings, and duplicated points.
- Keep titles concise and technical.
- Mark vague or ambiguous work with "is_unclear": true and category "Unknown".
- Detect meetings, syncs, standups, grooming, and handoffs as category "Meeting".
- Do not invent Jira ticket IDs, code changes, or files not present in the notes.

Developer notes:
{json.dumps(notes)}
""".strip()


def task_to_ticket_prompt(tasks: list[StructuredTask], tickets: list[JiraTicket], threshold: float) -> str:
    task_payload = [
        {
            "task_index": index,
            "title": task.title,
            "category": task.category.value,
            "details": task.details,
            "is_unclear": task.is_unclear,
        }
        for index, task in enumerate(tasks)
    ]
    ticket_payload = [
        {
            "ticket_id": ticket.ticket_id,
            "summary": ticket.summary,
            "description": ticket.description,
        }
        for ticket in tickets
    ]
    return f"""
Map each structured task to the single best Jira ticket.

Rules:
- Return strict JSON only.
- Output a top-level object with a single key: "mappings".
- Each mapping must follow: {{"task_index": integer, "ticket_id": string, "confidence": number, "reasoning": string}}.
- Use semantic similarity and keyword relevance against the ticket summary and description.
- If confidence is below {threshold}, return "UNMAPPED" for that task.
- Keep confidence between 0 and 1.
- Meetings should return "UNMAPPED".
- Do not invent ticket IDs that are not in the provided ticket list.

Tasks:
{json.dumps(task_payload)}

Candidate Jira tickets:
{json.dumps(ticket_payload)}
""".strip()


def time_estimation_prompt(mappings: list[TaskTicketMatch], tasks: list[StructuredTask], working_hours: float) -> str:
    task_payload = [
        {
            "task_index": mapping.task_index,
            "ticket_id": mapping.ticket_id,
            "task_title": mapping.task_title,
            "category": tasks[mapping.task_index].category.value,
            "details": tasks[mapping.task_index].details,
        }
        for mapping in mappings
    ]
    return f"""
Distribute the developer's total working hours across the provided tasks.

Rules:
- Return strict JSON only.
- Output a top-level object with a single key: "allocations".
- Each allocation must follow: {{"task_index": integer, "time_hours": number}}.
- The sum of all time_hours must equal exactly {working_hours}.
- Backend and Validation work should usually receive more time than minor UI tweaks.
- Meetings must remain separate from Jira tickets.
- Avoid assigning zero time to tasks unless they are obvious duplicates.
- Do not invent tasks or change task indices.

Tasks to allocate:
{json.dumps(task_payload)}
""".strip()
