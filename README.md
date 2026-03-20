# AI Jira Worklog Assistant

Production-ready FastAPI backend for converting raw developer notes into structured Jira worklog suggestions.

## Folder structure

```text
.
|-- app
|   |-- cli.py
|   |-- core
|   |   |-- config.py
|   |   `-- logging.py
|   |-- main.py
|   |-- models
|   |   `-- schemas.py
|   |-- prompts
|   |   `-- templates.py
|   |-- routes
|   |   `-- process_notes.py
|   `-- services
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
`-- pyproject.toml
```

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` to enable LLM parsing and mapping. Set `JIRA_USE_MOCK=false` and provide Jira credentials to call Jira Cloud.

## Run the API

```powershell
uvicorn app.main:app --reload
```

## Example API request

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/process `
  -Method Post `
  -ContentType "application/json" `
  -Body (Get-Content examples/process_request.json -Raw)
```

## Example CLI usage

```powershell
python -m app.cli --notes-file examples/notes.txt --working-hours 8
```
