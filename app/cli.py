from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.routes.process_notes import get_orchestrator


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process developer notes into Jira worklog suggestions.")
    parser.add_argument("--notes", help="Raw notes to process.")
    parser.add_argument("--notes-file", type=Path, help="Path to a text file containing raw notes.")
    parser.add_argument("--working-hours", type=float, required=True, help="Total working hours for the day.")
    return parser


async def _run() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    notes = args.notes
    if args.notes_file:
        notes = args.notes_file.read_text(encoding="utf-8")

    if not notes or not notes.strip():
        parser.error("Either --notes or --notes-file with non-empty content is required.")

    orchestrator = get_orchestrator()
    result = await orchestrator.process(notes=notes, working_hours=args.working_hours)
    print(result.model_dump_json(indent=2))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
