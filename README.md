# AI Jira Worklog Assistant

AI Jira Worklog Assistant is a Python backend that converts raw developer notes into Jira-ready worklog suggestions. It parses messy notes, maps the work to active Jira tickets, estimates time allocation, and returns clean ticket updates plus clearly separated unmapped work.

## Features

- FastAPI API with `POST /process`
- OpenAI-backed note parsing, ticket mapping, and time estimation
- Deterministic fallbacks when the LLM is unavailable
- Jira Cloud integration with mock-data support
- Pydantic request and response validation
- CLI entrypoint for local use and automation
- Clear handling for vague notes, meetings, and low-confidence ticket matches

## Tech stack

- Python 3.10+
- FastAPI
- OpenAI API
- Jira REST API
- Pydantic
- httpx

## Folder structure

```text
.
|-- app
|   |-- cli.py
|   |-- main.py
|   |-- core
|   |   |-- __init__.py
|   |   |-- config.py
|   |   `-- logging.py
|   |-- models
|   |   |-- __init__.py
|   |   `-- schemas.py
|   |-- prompts
|   |   |-- __init__.py
|   |   `-- templates.py
|   |-- routes
|   |   |-- __init__.py
|   |   `-- process_notes.py
|   `-- services
|       |-- __init__.py
|       |-- jira_client.py
|       |-- note_parser.py
|       |-- openai_client.py
|       |-- task_mapper.py
|       |-- time_estimator.py
|       `-- worklog_orchestrator.py
|-- data
|   `-- mock_jira_tickets.json
|-- examples
|   |-- notes.txt
|   `-- process_request.json
|-- .env.example
|-- pyproject.toml
`-- README.md
```

## Processing pipeline

1. Input
   - Raw notes
   - Jira tickets from Jira Cloud or mock JSON
   - Total working hours
2. Note parsing
   - Extracts structured tasks
   - Groups related work
   - Removes noise and marks unclear items
3. Task mapping
   - Uses lexical scoring plus optional LLM semantic mapping
   - Rejects matches below the confidence threshold
4. Time estimation
   - Allocates hours across tasks
   - Keeps the total equal to the input working hours
   - Keeps meetings separate
5. Final output
   - Jira-ready updates per ticket
   - Time suggestion per mapped ticket
   - Unmapped work called out explicitly

## Environment variables

Copy `.env.example` to `.env` and update values as needed.

```env
APP_NAME=AI Jira Worklog Assistant
LOG_LEVEL=INFO

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
LLM_TIMEOUT_SECONDS=45

JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=developer@example.com
JIRA_API_TOKEN=
JIRA_USE_MOCK=true
JIRA_MOCK_DATA_PATH=data/mock_jira_tickets.json
JIRA_CACHE_TTL_SECONDS=300
```

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

## Run the API

```powershell
uvicorn app.main:app --reload
```

## Run the UI

Install the optional UI dependency if needed:

```powershell
pip install -e .[ui]
```

Start the Streamlit app:

```powershell
streamlit run app/ui.py
```

The UI lets you:

- filter assigned tickets by project prefix such as `GA` or `ILPQC`
- preview matching tickets in a table
- paste raw notes and generate Jira-ready worklogs
- inspect unmapped work and raw JSON output

API base URL:

```text
http://127.0.0.1:8000
```

Health check:

```text
GET /health
```

Processing endpoint:

```text
POST /process
```

## API request example

Example file:

```text
examples/process_request.json
```

Request body:

```json
{
  "notes": "Investigated JWT refresh failures after idle timeout. Added null checks and request validation around session payload handling. Fixed dashboard skeleton loader flicker on slow responses. Synced with QA on bulk upload regression and next test cycle.",
  "working_hours": 8
}
```

PowerShell example:

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/process `
  -Method Post `
  -ContentType "application/json" `
  -Body (Get-Content examples/process_request.json -Raw)
```

## Response shape

```json
{
  "tickets": [
    {
      "ticket_id": "JIRA-101",
      "time_hours": 2.21,
      "updates": [
        "JWT refresh failures after idle timeout."
      ]
    }
  ],
  "unmapped": [
    {
      "title": "Synced with QA on bulk upload regression and next test",
      "details": [
        "Synced with QA on bulk upload regression and next test cycle"
      ],
      "reason": "Meeting work is tracked separately from Jira tickets.",
      "suggested_time_hours": 1.2
    }
  ]
}
```

## CLI usage

```powershell
python -m app.cli --notes-file examples/notes.txt --working-hours 8
```

You can also pass notes inline:

```powershell
python -m app.cli --notes "Fixed auth refresh bug and updated validation flow" --working-hours 8
```

## Jira integration

When `JIRA_USE_MOCK=false`, the service calls Jira Cloud:

- Endpoint: `GET /rest/api/3/search`
- JQL: `assignee = currentUser() AND status != Done`
- Fields extracted:
  - issue key
  - summary
  - description

Authentication is token-based using Jira email plus API token.

## Mock mode

Mock mode is enabled by default so the service runs without external dependencies. Tickets are loaded from:

```text
data/mock_jira_tickets.json
```

## Verification

Useful local verification commands:

```powershell
python -m compileall app
python -m app.cli --notes-file examples/notes.txt --working-hours 8
python -c "from app.main import app; print(app.title)"
```

## Notes

- Empty notes return a validation error.
- Low-confidence ticket matches are returned under `unmapped`.
- Meetings are intentionally left unmapped.
- If OpenAI is not configured, the system still runs using deterministic fallbacks.
