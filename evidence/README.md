# Submission evidence

This directory contains reviewed evidence from genuine OpenAI-guided discovery runs and deterministic artifact replay. Every retained set uses `"mode": "openai"`; mock output is not presented as assignment evidence.

| Scenario | Discovery log | Compiled artifact | Replay result |
|---|---|---|---|
| Successful extraction | `discovery-success.jsonl` | `artifact-success.json` | `replay-success.json` |
| Business outcome | `discovery-business-outcome.jsonl` | `artifact-business-outcome.json` | `replay-business-outcome.json` |
| Hard failure | `discovery-hard-failure.jsonl` | `artifact-hard-failure.json` | `replay-hard-failure.json` |

`hard-failure-redacted-dom.html` is the redacted rich failure signal retained for the hard-failure example.

Discovery logs show the observe-decide-act sequence without storing typed values or page body text. Artifacts contain `{{member_id}}` rather than the example input. Replay files retain the status, output shape, state code, step, and checkpoint details while redacting output values and runtime record identifiers.

To generate fresh evidence, configure `OPENAI_API_KEY`, start the target app on port `8001`, and run:

```powershell
python -m app.smokes.full_system_smoke
```

Alternatively, start both applications and submit the real OpenAI workflow from `http://127.0.0.1:8000`. Review every new file before publishing it. Confirm that no API key, token, raw member ID, member name, or balance is present.
