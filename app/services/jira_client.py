from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.models.schemas import JiraTicket

LOGGER = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: tuple[float, list[JiraTicket]] | None = None

    async def get_assigned_tickets(self, project_key: str | None = None) -> list[JiraTicket]:
        now = time.time()
        if self._cache and (now - self._cache[0]) < self._settings.jira_cache_ttl_seconds:
            LOGGER.debug("Returning Jira tickets from cache.")
            return self._filter_tickets(self._cache[1], project_key)

        tickets = await self._load_mock_tickets() if self._settings.jira_use_mock else await self._fetch_jira_tickets()
        self._cache = (now, tickets)
        return self._filter_tickets(tickets, project_key)

    async def _load_mock_tickets(self) -> list[JiraTicket]:
        mock_path = Path(self._settings.jira_mock_data_path)
        if not mock_path.exists():
            raise RuntimeError(f"Mock Jira data file not found: {mock_path}")

        payload = json.loads(mock_path.read_text(encoding="utf-8"))
        issues = payload["issues"] if isinstance(payload, dict) else payload
        tickets = [self._parse_issue(issue) for issue in issues]
        LOGGER.info("Loaded %s mock Jira tickets from %s", len(tickets), mock_path)
        return tickets

    async def _fetch_jira_tickets(self) -> list[JiraTicket]:
        if not self._settings.jira_base_url or not self._settings.jira_email or not self._settings.jira_api_token:
            raise RuntimeError("Jira credentials are incomplete. Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN.")

        auth_value = base64.b64encode(
            f"{self._settings.jira_email}:{self._settings.jira_api_token}".encode("utf-8")
        ).decode("utf-8")
        headers = {
            "Authorization": f"Basic {auth_value}",
            "Accept": "application/json",
        }
        params = {
            "jql": "assignee = currentUser() AND status != Done",
            "fields": "summary,description",
            "maxResults": 100,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(self._settings.jira_search_url, headers=headers, params=params)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Jira request failed with status {response.status_code}: {response.text}") from exc

        payload = response.json()
        issues = payload.get("issues", [])
        tickets = [self._parse_issue(issue) for issue in issues]
        LOGGER.info("Fetched %s Jira tickets from Jira Cloud", len(tickets))
        return tickets

    def _parse_issue(self, issue: dict[str, Any]) -> JiraTicket:
        fields = issue.get("fields", {})
        return JiraTicket(
            issue_key=issue["key"],
            summary=fields.get("summary", "").strip(),
            description=self._extract_description(fields.get("description")),
        )

    def _extract_description(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return " ".join(self._collect_text(value)).strip()
        if isinstance(value, list):
            text_parts: list[str] = []
            for item in value:
                text_parts.extend(self._collect_text(item))
            return " ".join(text_parts).strip()
        return str(value).strip()

    def _collect_text(self, node: Any) -> list[str]:
        if isinstance(node, dict):
            values: list[str] = []
            text_value = node.get("text")
            if text_value:
                values.append(str(text_value))
            content = node.get("content", [])
            for child in content:
                values.extend(self._collect_text(child))
            return values
        if isinstance(node, list):
            values: list[str] = []
            for child in node:
                values.extend(self._collect_text(child))
            return values
        return []

    def _filter_tickets(self, tickets: list[JiraTicket], project_key: str | None) -> list[JiraTicket]:
        if not project_key:
            return tickets
        normalized_prefix = project_key.strip().upper()
        ticket_prefix = f"{normalized_prefix}-"
        filtered = [ticket for ticket in tickets if ticket.ticket_id.upper().startswith(ticket_prefix)]
        LOGGER.info("Filtered Jira tickets by prefix %s: %s matched", normalized_prefix, len(filtered))
        return filtered
