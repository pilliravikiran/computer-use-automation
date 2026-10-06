# Computer-Use Automation System

This project demonstrates an OpenAI-guided workflow discovery followed by deterministic replay. The target member-management application runs on port `8001`, and the automation control application runs on port `8000`.

## How to run

### 1. Install the project

Requirements: Python 3.11 or newer and an OpenAI API key for real LLM discovery.

Open PowerShell in the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m playwright install chromium
Copy-Item .env.example .env
```

Open `.env` and add your API key:

```text
OPENAI_API_KEY=your-key-here
```

Do not commit `.env`. Set `HEADLESS=false` if you want to watch the browser automation.

### 2. Start the target application

Open the first terminal, activate the virtual environment, and run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn demo_app.main:app --host 127.0.0.1 --port 8001
```

The member-management application is now available at [http://127.0.0.1:8001](http://127.0.0.1:8001).

### 3. Start the control application

Open a second terminal, activate the virtual environment, and run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Uvicorn starts the server but does not automatically open a browser. Manually open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### 4. Run the main demonstration

Select **Real OpenAI-guided discovery** and enter:

```text
Goal: Look up the member and return the current savings balance.
Target URL: http://localhost:8001
Discovery member ID: 12345
Replay member ID: 67890
```

Click **Start Complete Workflow**. Two browser runs occur:

1. Discovery uses member `12345` and asks OpenAI to choose the browser actions.
2. Replay loads the saved artifact and executes it with member `67890` without LLM decisions.

For a demonstration without an API key, select **Credential-free scripted model decisions**. Browser interaction, recording, artifact compilation, replay, state classification, and cleanup still execute normally.

## How the system flows

```text
User opens port 8000
        |
        v
workflow_home.html
        |
        | POST /workflows/member-savings
        v
MemberSavingsWorkflowService
        |
        +--> DiscoveryAgent
        |       |
        |       +--> OpenAI or mock provider chooses actions
        |       +--> Playwright performs actions on port 8001
        |       +--> DiscoveryRecorder records successful steps
        |
        +--> ArtifactCompiler
        |       |
        |       +--> replaces example values with {{member_id}}
        |       +--> creates a typed, versioned JSON artifact
        |
        +--> ReplayEngine
        |       |
        |       +--> loads the saved artifact
        |       +--> inserts the new runtime member ID
        |       +--> executes saved actions without an LLM
        |       +--> classifies success, business outcomes, and failures
        |
        +--> EvidenceWriter
                |
                +--> writes redacted discovery, artifact, and replay evidence
```

The control application stores current progress in `RunManager` and `RunSession`. The status page reloads while the background workflow is running and displays the latest stage.

## HTML pages used by port 8000

| URL | Method in `app/main.py` | HTML template | Purpose |
|---|---|---|---|
| `/` | `home` | `workflow_home.html` | Shows the workflow form and recent runs |
| `/runs/{run_id}/view` | `run_status_page` | `workflow_run.html` | Shows live progress, the artifact, and the final result |
| `/operator/runs/{run_id}` | `operator_run` | `operator_run.html` | Shows human-intervention controls |

The starting point is `app/main.py`. When `/` is requested, the `home()` method reads the current sessions from `RunManager` and renders `workflow_home.html`. Submitting the form creates a `RunSession`, starts the workflow in the background, and redirects to `workflow_run.html`.

## Test cases to demonstrate

Keep discovery member ID `12345` and change the replay member ID:

| Replay ID | Expected result |
|---|---|
| `67890` | Successful replay and savings balance extraction |
| `99999` | Business outcome: `MEMBER_NOT_FOUND` |
| `88888` | Hard failure: `PERMISSION_DENIED` |
| `77777` | Slow result; replay waits without clicking twice |
| `66666` | `SESSION_EXPIRED`; session is restored and the sequence restarts |
| `55555` | `SYSTEM_NOTICE`; the notice is dismissed and replay continues |
| `55550` | Unknown security page; automation pauses for human intervention |

For member `55550`:

1. Open the intervention controls.
2. Click **Take Control**.
3. In the existing automation browser, click **Verify Identity**.
4. Return to the operator page and click **Resume Automation**.
5. The same replay task checks the updated page and continues.

If you click **Abort**, the run ends with `OPERATOR_ABORTED`, the Playwright browser closes, and the control app returns to the home page. **Resume Automation** remains disabled until **Take Control** has transferred ownership to the human.

Safe metadata about the human's actions is written to `evidence/human-actions-{run_id}.json`. Typed values are not captured, and record identifiers are redacted before the file is saved.

## Command-line demonstrations

Keep the port-`8001` application running before using these commands.

Real OpenAI discovery and deterministic replay:

```powershell
python -m app.smokes.full_system_smoke
```

Replay the newest saved artifact with a different input:

```powershell
python -m app.smokes.saved_artifact_replay_smoke 67890
```

Offline end-to-end demonstration:

```powershell
python -m app.smokes.end_to_end_artifact_replay_smoke
```

Human handoff demonstration:

```powershell
python -m app.smokes.normal_app_handoff_smoke
```

## API

`POST /api/workflows/member-savings` starts the same workflow used by the HTML form:

```json
{
  "mode": "openai",
  "goal": "Look up the member and return the current savings balance.",
  "target_url": "http://localhost:8001",
  "discovery_member_id": "12345",
  "replay_member_id": "67890"
}
```

Use `GET /runs/{run_id}` to retrieve the status, current stage, stage history, structured replay result, artifact version, human-action metadata, and evidence paths. Hard failures retain their code, failed step, expected checkpoint, and observed state in `result.replay_result`.

## Run code checks

```powershell
python -m ruff check .
python -m compileall -q app demo_app
```

The checked-in [`evidence`](evidence/README.md) directory contains redacted genuine OpenAI discovery and deterministic replay examples.

## Project layout

```text
app/                 control server, discovery, replay, safety, and handoff code
app/templates/       HTML pages used by the port-8000 control application
app/smokes/          evaluator-facing end-to-end demonstrations
demo_app/            local member-management target application
evidence/            reviewed and redacted execution evidence
README.md            setup, run, flow, and verification instructions
```

Runtime artifacts are written to the ignored `artifacts/` directory. Local environments, `.env`, IDE settings, caches, and build output are also excluded from Git.
