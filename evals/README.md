# MCP Eval Harness

A model-agnostic benchmark for how well an AI operator actually uses this MCP server. It answers: **task success rate, tool-selection accuracy, output variability, efficiency (turns/tokens/latency), and confusion signals** — per model, on the *live* server.

It's the baseline you measure *before* deciding which of the 42 tools to consolidate, demote, or hide behind progressive disclosure.

## Why model-agnostic

The harness is itself the MCP client (official `mcp` SDK, Streamable HTTP). Each model is a thin adapter that gets the **same** tool list through the **same** agentic loop, so Claude and DeepSeek are measured identically — not through Claude's built-in connector vs a hand-rolled loop. Adding a model = adding an adapter.

Currently wired: **Claude** (`anthropic`) and **DeepSeek V4 Flash via Ollama Cloud** (`openai` SDK → `https://ollama.com/v1`).

## Setup

```bash
cd evals
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in keys + a token (below)
```

### Getting an MCP token

The hosted MCP uses Cognito OAuth. Claude Code does that via an interactive browser flow; a headless harness can't. Two paths:

- **(B) Fastest — grab a token.** Connect the connector once in Claude Code (or any browser OAuth), and use the resulting access token. Set `FR_MCP_TOKEN=...`. Expires ~1h; fine for a manual run.
- **(A) Repeatable / CI — mint from a test account.** `export FR_MCP_TOKEN="$(python cognito_token.py)"` using the test account creds + the Cognito app client id the MCP accepts (`MCP_COGNITO_CLIENT_IDS` — ask the FR team; a token for the wrong client is rejected by the audience check). Needs `ALLOW_USER_PASSWORD_AUTH` on that client.

## Run

```bash
python run_eval.py --models claude --runs 3            # Claude only
python run_eval.py --models claude,deepseek --runs 5   # cross-model, 5× for variability
```

Writes `out/scorecard.md` (+ `.json`) and prints the markdown. `--runs N` is the variability sample size; N≥5 recommended for the consistency metrics to mean anything.

## What the metrics mean

| Metric | Reads as |
|---|---|
| **Success rate** | fraction of runs graded pass (deterministic `assert_contains`, else LLM judge against the task's rubric) |
| **First-tool accuracy** | did the run open with an expected tool? (selection at the decision point) |
| **Selection accuracy** | expected-tool coverage minus forbidden-tool penalty |
| **Path consistency** | variability — do repeats take the same tool route? |
| **Outcome consistency** | variability — do repeats reach the same verdict? (flapping = trust risk on a financial product) |
| **Mean turns / tokens / latency** | efficiency |
| **Errored / retries / forbidden** | confusion signals |
| **Tool usage frequency + never-used** | the pruning signal — which tools earn their context cost |

## Adding tasks

Drop a YAML file in `tasks/` (one task or a `tasks:` list). Fields: `id`, `prompt`, `domain`, `expected_tools`, `forbidden_tools`, `assert_contains` (deterministic ground truth), `success_rubric` (judge criteria). See `tasks/core.yaml`.

## Tests

The deterministic core (task loading, scoring, grading logic) has unit tests that run with no secrets:

```bash
pytest tests/ -q
```

The model adapters / MCP client are exercised by an actual `run_eval.py` run against the live server (needs a token).

## Layout

```
evals/
  run_eval.py          CLI
  cognito_token.py     token path A helper
  tasks/*.yaml         benchmark tasks
  harness/
    mcp_client.py      Streamable-HTTP MCP client (bearer)
    models.py          Claude + OpenAI-compatible(DeepSeek) adapters
    grader.py          deterministic asserts + LLM judge
    scorer.py          pure metric functions
    results.py         RunResult / ToolCall data model
    runner.py          orchestration
    report.py          markdown + JSON scorecard
  tests/               unit tests for the pure layer
```
