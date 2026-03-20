from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.models.schemas import ParseTasksLLMResponse, StructuredTask, TaskCategory
from app.prompts.templates import notes_to_tasks_prompt
from app.services.openai_client import OpenAIJSONClient

LOGGER = logging.getLogger(__name__)

STOPWORDS = {
    "a",
    "an",
    "and",
    "around",
    "for",
    "from",
    "into",
    "of",
    "on",
    "the",
    "to",
    "with",
    "updated",
    "worked",
    "working",
    "fixed",
    "added",
    "handled",
    "handling",
}


@dataclass
class _TaskGroup:
    title: str
    category: TaskCategory
    details: list[str] = field(default_factory=list)
    tokens: set[str] = field(default_factory=set)
    is_unclear: bool = False


class NoteParserService:
    def __init__(self, openai_client: OpenAIJSONClient) -> None:
        self._openai_client = openai_client

    async def parse_notes(self, notes: str) -> list[StructuredTask]:
        cleaned_notes = notes.strip()
        if not cleaned_notes:
            raise ValueError("Notes must not be empty.")

        if self._openai_client.enabled:
            try:
                response = await self._openai_client.generate_json(notes_to_tasks_prompt(cleaned_notes))
                parsed = ParseTasksLLMResponse.model_validate(response)
                if parsed.tasks:
                    return parsed.tasks
            except (RuntimeError, ValidationError) as exc:
                LOGGER.warning("LLM note parsing failed, falling back to heuristics: %s", exc)

        tasks = self._heuristic_parse(cleaned_notes)
        if not tasks:
            raise ValueError("Unable to extract meaningful tasks from notes.")
        return tasks

    def _heuristic_parse(self, notes: str) -> list[StructuredTask]:
        fragments = self._extract_fragments(notes)
        groups: list[_TaskGroup] = []

        for fragment in fragments:
            if self._is_noise(fragment):
                continue

            category = self._classify_category(fragment)
            is_unclear = self._is_unclear(fragment)
            tokens = self._topic_tokens(fragment)

            matched_group = None
            for group in groups:
                overlap = self._token_overlap(tokens, group.tokens)
                if group.category == category and overlap >= 0.35:
                    matched_group = group
                    break

            if matched_group:
                if fragment not in matched_group.details and fragment != matched_group.title:
                    matched_group.details.append(fragment)
                matched_group.tokens.update(tokens)
                matched_group.is_unclear = matched_group.is_unclear or is_unclear
                continue

            title = self._build_title(fragment, category, is_unclear)
            detail_items = [] if title == fragment else [fragment]
            groups.append(
                _TaskGroup(
                    title=title,
                    category=category,
                    details=detail_items,
                    tokens=tokens,
                    is_unclear=is_unclear,
                )
            )

        return [
            StructuredTask(
                title=group.title,
                category=group.category,
                details=self._deduplicate(group.details),
                is_unclear=group.is_unclear,
            )
            for group in groups
        ]

    def _extract_fragments(self, notes: str) -> list[str]:
        normalized = notes.replace("\r\n", "\n").replace("\r", "\n")
        fragments: list[str] = []
        for raw_line in normalized.split("\n"):
            line = re.sub(r"^\s*[-*\d.)]+\s*", "", raw_line).strip()
            if not line:
                continue
            for part in re.split(r"\s*[;|]\s*", line):
                candidate = part.strip()
                if candidate:
                    fragments.append(candidate)
        if len(fragments) <= 1:
            sentence_parts = re.split(r"(?<=[.!?])\s+", normalized)
            fragments = [part.strip(" -") for part in sentence_parts if part.strip()]
        return fragments

    def _classify_category(self, text: str) -> TaskCategory:
        lower = text.lower()
        if any(keyword in lower for keyword in {"meeting", "sync", "standup", "grooming", "discussion", "handoff"}):
            return TaskCategory.MEETING
        if any(keyword in lower for keyword in {"validation", "validator", "sanitize", "null check", "schema"}):
            return TaskCategory.VALIDATION
        if any(keyword in lower for keyword in {"refactor", "cleanup", "restructure", "simplified"}):
            return TaskCategory.REFACTOR
        if any(keyword in lower for keyword in {"fix", "bug", "issue", "failure", "regression", "investigated"}):
            return TaskCategory.BUGFIX
        if any(keyword in lower for keyword in {"ui", "frontend", "dashboard", "layout", "loader", "screen"}):
            return TaskCategory.UI
        if any(keyword in lower for keyword in {"api", "backend", "auth", "token", "middleware", "service"}):
            return TaskCategory.BACKEND
        return TaskCategory.UNKNOWN

    def _build_title(self, fragment: str, category: TaskCategory, is_unclear: bool) -> str:
        cleaned = re.sub(
            r"^(worked on|working on|handled|handling|investigated|looked into|updated|added|fixed|implemented)\s+",
            "",
            fragment,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = cleaned[:1].upper() + cleaned[1:] if cleaned else fragment
        words = cleaned.split()
        title = " ".join(words[:10]).strip(".,")
        if is_unclear and len(words) < 4:
            return f"Clarify work item: {title}"
        if category == TaskCategory.MEETING and "meeting" not in title.lower() and "sync" not in title.lower():
            return f"Meeting: {title}"
        return title

    def _topic_tokens(self, text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-zA-Z0-9]+", text.lower())
            if len(token) > 2 and token not in STOPWORDS
        }

    def _token_overlap(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / max(min(len(left), len(right)), 1)

    def _is_noise(self, text: str) -> bool:
        lower = text.lower().strip(" .")
        return lower in {"misc", "etc", "general work", "updates"} or len(lower) < 3

    def _is_unclear(self, text: str) -> bool:
        lower = text.lower()
        vague_terms = {"misc", "stuff", "various", "some work", "helped out", "support"}
        token_count = len(re.findall(r"[a-zA-Z0-9]+", lower))
        return token_count < 3 or any(term in lower for term in vague_terms)

    def _deduplicate(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for value in values:
            normalized = value.strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                output.append(normalized)
        return output
