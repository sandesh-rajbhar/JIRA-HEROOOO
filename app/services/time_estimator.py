from __future__ import annotations

import logging

from pydantic import ValidationError

from app.models.schemas import (
    StructuredTask,
    TaskCategory,
    TaskTicketMatch,
    TaskTimeAllocation,
    TimeEstimationLLMResponse,
)
from app.prompts.templates import time_estimation_prompt
from app.services.openai_client import OpenAIJSONClient

LOGGER = logging.getLogger(__name__)


class TimeEstimatorService:
    def __init__(self, openai_client: OpenAIJSONClient) -> None:
        self._openai_client = openai_client

    async def estimate(
        self,
        tasks: list[StructuredTask],
        mappings: list[TaskTicketMatch],
        total_hours: float,
    ) -> list[TaskTimeAllocation]:
        if total_hours <= 0:
            raise ValueError("Working hours must be greater than zero.")
        if not tasks:
            return []

        llm_allocations = await self._llm_estimate(tasks, mappings, total_hours)
        if llm_allocations:
            return self._normalize_allocations(mappings, total_hours, llm_allocations)

        weights = [self._task_weight(tasks[mapping.task_index], mapping) for mapping in mappings]
        weight_sum = sum(weights) or float(len(weights))
        raw_allocations = [total_hours * (weight / weight_sum) for weight in weights]
        return self._normalize_allocations(mappings, total_hours, raw_allocations)

    async def _llm_estimate(
        self,
        tasks: list[StructuredTask],
        mappings: list[TaskTicketMatch],
        total_hours: float,
    ) -> list[float]:
        if not self._openai_client.enabled:
            return []

        try:
            response = await self._openai_client.generate_json(time_estimation_prompt(mappings, tasks, total_hours))
            parsed = TimeEstimationLLMResponse.model_validate(response)
            if len(parsed.allocations) != len(mappings):
                raise ValueError("LLM returned an allocation count that does not match the task count.")

            allocations_by_index = {allocation.task_index: allocation.time_hours for allocation in parsed.allocations}
            return [allocations_by_index.get(index, 0.0) for index in range(len(mappings))]
        except (RuntimeError, ValidationError, ValueError) as exc:
            LOGGER.warning("LLM time estimation failed, using deterministic allocation: %s", exc)
            return []

    def _normalize_allocations(
        self,
        mappings: list[TaskTicketMatch],
        total_hours: float,
        raw_allocations: list[float],
    ) -> list[TaskTimeAllocation]:
        rounded = [round(max(value, 0.0), 2) for value in raw_allocations]
        current_total = round(sum(rounded), 2)
        difference = round(total_hours - current_total, 2)

        remainders = sorted(
            range(len(raw_allocations)),
            key=lambda index: raw_allocations[index] - rounded[index],
            reverse=difference > 0,
        )
        unit = 0.01
        while abs(difference) >= unit / 2 and remainders:
            for index in remainders:
                if abs(difference) < unit / 2:
                    break
                adjustment = unit if difference > 0 else -unit
                new_value = rounded[index] + adjustment
                if new_value < 0:
                    continue
                rounded[index] = round(new_value, 2)
                difference = round(difference - adjustment, 2)

        allocations: list[TaskTimeAllocation] = []
        for index, mapping in enumerate(mappings):
            bucket_id = mapping.ticket_id if mapping.ticket_id != "UNMAPPED" else f"UNMAPPED:{index}"
            allocations.append(
                TaskTimeAllocation(
                    task_index=index,
                    bucket_id=bucket_id,
                    time_hours=rounded[index],
                )
            )

        total_allocated = round(sum(item.time_hours for item in allocations), 2)
        if total_allocated != round(total_hours, 2):
            raise ValueError(f"Time allocation failed normalization. Expected {total_hours}, got {total_allocated}.")
        return allocations

    def _task_weight(self, task: StructuredTask, mapping: TaskTicketMatch) -> float:
        category_weights = {
            TaskCategory.BACKEND: 1.35,
            TaskCategory.VALIDATION: 1.25,
            TaskCategory.BUGFIX: 1.15,
            TaskCategory.REFACTOR: 1.0,
            TaskCategory.UI: 0.8,
            TaskCategory.MEETING: 0.65,
            TaskCategory.UNKNOWN: 0.55,
        }
        weight = category_weights.get(task.category, 0.7)
        weight += min(len(task.details) * 0.12, 0.36)
        if mapping.ticket_id == "UNMAPPED":
            weight *= 0.9
        if task.is_unclear:
            weight *= 0.75
        return max(weight, 0.2)
