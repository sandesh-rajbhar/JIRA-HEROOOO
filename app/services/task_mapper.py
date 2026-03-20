from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from pydantic import ValidationError

from app.core.config import Settings
from app.models.schemas import JiraTicket, StructuredTask, TaskCategory, TaskMappingLLMResponse, TaskTicketMatch
from app.prompts.templates import task_to_ticket_prompt
from app.services.openai_client import OpenAIJSONClient

LOGGER = logging.getLogger(__name__)
GENERIC_TOKENS = {
    "added",
    "around",
    "error",
    "failure",
    "fixed",
    "handling",
    "implement",
    "improve",
    "issue",
    "request",
    "slow",
    "state",
    "update",
    "work",
}
STRONG_DOMAIN_TOKENS = {
    "auth",
    "bulk",
    "dashboard",
    "load",
    "middleware",
    "payload",
    "profile",
    "refresh",
    "regression",
    "session",
    "token",
    "upload",
    "validation",
}


class TaskMapperService:
    def __init__(self, settings: Settings, openai_client: OpenAIJSONClient) -> None:
        self._settings = settings
        self._openai_client = openai_client

    async def map_tasks(self, tasks: list[StructuredTask], tickets: list[JiraTicket]) -> list[TaskTicketMatch]:
        if not tickets:
            return [
                TaskTicketMatch(
                    task_index=index,
                    task_title=task.title,
                    ticket_id="UNMAPPED",
                    confidence=0.0,
                    reasoning="No Jira tickets were available for mapping.",
                )
                for index, task in enumerate(tasks)
            ]

        local_scores: dict[int, list[tuple[JiraTicket, float]]] = {}
        for index, task in enumerate(tasks):
            scored_tickets = [(ticket, self._local_score(task, ticket)) for ticket in tickets]
            local_scores[index] = sorted(scored_tickets, key=lambda item: item[1], reverse=True)

        llm_mappings = await self._llm_map(tasks, local_scores)

        matches: list[TaskTicketMatch] = []
        for index, task in enumerate(tasks):
            if task.category == TaskCategory.MEETING:
                matches.append(
                    TaskTicketMatch(
                        task_index=index,
                        task_title=task.title,
                        ticket_id="UNMAPPED",
                        confidence=0.0,
                        reasoning="Meeting work is tracked separately from Jira tickets.",
                    )
                )
                continue

            best_local_ticket, best_local_score = local_scores[index][0]
            llm_mapping = llm_mappings.get(index)
            chosen_ticket = best_local_ticket.ticket_id
            chosen_score = best_local_score
            reasoning = f"Highest local similarity matched {best_local_ticket.ticket_id}."

            if llm_mapping:
                reasoning = llm_mapping.reasoning
                if llm_mapping.ticket_id == "UNMAPPED":
                    chosen_ticket = "UNMAPPED"
                    chosen_score = min(best_local_score, llm_mapping.confidence)
                else:
                    llm_local_score = self._score_for_ticket(local_scores[index], llm_mapping.ticket_id)
                    combined_score = max(llm_local_score, round((0.45 * llm_local_score) + (0.55 * llm_mapping.confidence), 4))
                    if combined_score >= chosen_score or llm_mapping.ticket_id == chosen_ticket:
                        chosen_ticket = llm_mapping.ticket_id
                        chosen_score = combined_score

            if task.is_unclear or chosen_score < self._settings.mapping_confidence_threshold:
                chosen_ticket = "UNMAPPED"
                reasoning = "Confidence below threshold or task details are too vague to map safely."

            matches.append(
                TaskTicketMatch(
                    task_index=index,
                    task_title=task.title,
                    ticket_id=chosen_ticket,
                    confidence=round(min(max(chosen_score, 0.0), 1.0), 4),
                    reasoning=reasoning,
                )
            )

        return matches

    async def _llm_map(
        self,
        tasks: list[StructuredTask],
        local_scores: dict[int, list[tuple[JiraTicket, float]]],
    ) -> dict[int, TaskTicketMatch]:
        if not self._openai_client.enabled:
            return {}

        candidate_ids: list[str] = []
        ticket_lookup: dict[str, JiraTicket] = {}
        for scored in local_scores.values():
            for ticket, _score in scored[:5]:
                if ticket.ticket_id not in ticket_lookup:
                    ticket_lookup[ticket.ticket_id] = ticket
                    candidate_ids.append(ticket.ticket_id)

        candidate_tickets = [ticket_lookup[ticket_id] for ticket_id in candidate_ids]

        try:
            response = await self._openai_client.generate_json(
                task_to_ticket_prompt(tasks, candidate_tickets, self._settings.mapping_confidence_threshold)
            )
            parsed = TaskMappingLLMResponse.model_validate(response)
            return {
                mapping.task_index: TaskTicketMatch(
                    task_index=mapping.task_index,
                    task_title=tasks[mapping.task_index].title,
                    ticket_id=mapping.ticket_id,
                    confidence=mapping.confidence,
                    reasoning=mapping.reasoning,
                )
                for mapping in parsed.mappings
                if 0 <= mapping.task_index < len(tasks)
            }
        except (RuntimeError, ValidationError) as exc:
            LOGGER.warning("LLM task mapping failed, using deterministic scores only: %s", exc)
            return {}

    def _local_score(self, task: StructuredTask, ticket: JiraTicket) -> float:
        task_text = " ".join([task.title, *task.details])
        ticket_text = f"{ticket.summary} {ticket.description}".strip()

        if re.search(rf"\b{re.escape(ticket.ticket_id.lower())}\b", task_text.lower()):
            return 1.0

        task_tokens = self._tokens(task_text)
        ticket_tokens = self._tokens(ticket_text)
        shared_tokens = task_tokens & ticket_tokens
        coverage = len(shared_tokens) / max(min(len(task_tokens), len(ticket_tokens)), 1)
        overlap = len(shared_tokens) / max(len(task_tokens | ticket_tokens), 1)
        title_similarity = SequenceMatcher(None, task.title.lower(), ticket.summary.lower()).ratio()
        detail_similarity = SequenceMatcher(None, task_text.lower(), ticket_text.lower()).ratio()
        category_boost = self._category_alignment(task.category, ticket_text.lower())
        phrase_boost = self._phrase_boost(task_text, ticket_text)
        shared_bonus = min(len(shared_tokens - GENERIC_TOKENS) * 0.08, 0.24)
        strong_bonus = 0.15 if shared_tokens & STRONG_DOMAIN_TOKENS else 0.0

        score = (
            (0.35 * coverage)
            + (0.2 * overlap)
            + (0.2 * title_similarity)
            + (0.1 * detail_similarity)
            + (0.15 * category_boost)
            + phrase_boost
            + shared_bonus
            + strong_bonus
        )
        if task.is_unclear:
            score *= 0.6
        return round(min(score, 1.0), 4)

    def _score_for_ticket(self, scores: list[tuple[JiraTicket, float]], ticket_id: str) -> float:
        for ticket, score in scores:
            if ticket.ticket_id == ticket_id:
                return score
        return 0.0

    def _tokens(self, value: str) -> set[str]:
        return {self._normalize_token(token) for token in re.findall(r"[a-zA-Z0-9]+", value.lower()) if len(token) > 2}

    def _category_alignment(self, category: TaskCategory, ticket_text: str) -> float:
        keyword_map = {
            TaskCategory.BACKEND: {"backend", "api", "service", "auth", "middleware"},
            TaskCategory.VALIDATION: {"validation", "schema", "payload", "error"},
            TaskCategory.BUGFIX: {"bug", "fix", "issue", "failure", "regression"},
            TaskCategory.REFACTOR: {"refactor", "cleanup", "simplify"},
            TaskCategory.UI: {"ui", "frontend", "component", "dashboard", "layout"},
        }
        keywords = keyword_map.get(category, set())
        if not keywords:
            return 0.0
        return 1.0 if any(keyword in ticket_text for keyword in keywords) else 0.0

    def _normalize_token(self, token: str) -> str:
        lowered = token.lower()
        for suffix in ("ing", "ers", "er", "ed", "es", "s"):
            if lowered.endswith(suffix) and len(lowered) - len(suffix) >= 4:
                lowered = lowered[: -len(suffix)]
                break
        normalization_map = {
            "authent": "auth",
            "flick": "flicker",
            "jwt": "token",
            "loader": "load",
            "loading": "load",
            "payloads": "payload",
            "regress": "regression",
            "validat": "validation",
        }
        return normalization_map.get(lowered, lowered)

    def _phrase_boost(self, task_text: str, ticket_text: str) -> float:
        lowered_ticket = ticket_text.lower()
        task_terms = [self._normalize_token(token) for token in re.findall(r"[a-zA-Z0-9]+", task_text.lower())]
        for index in range(len(task_terms) - 1):
            phrase = f"{task_terms[index]} {task_terms[index + 1]}".strip()
            if len(phrase) > 6 and phrase in lowered_ticket:
                return 0.12
        return 0.0
