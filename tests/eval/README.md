# Evals

The authoritative eval harness for this server is the private repo
[financial-reports/mcp-evals](https://github.com/financial-reports/mcp-evals).
It is model-agnostic (currently Claude + DeepSeek), measures task success
rate, tool-selection accuracy, path consistency, and efficiency, and runs
against any Streamable HTTP MCP URL.

The eval harness is the source of truth for "is this server good." Do not
build a parallel harness in this repo.

## What lives here

Only the **deterministic prompt-registration tests** —
`tests/eval/test_prompts_deterministic.py`.

These confirm that every Prompt we ship is actually registered with the
FastMCP server and that its rendered messages reference the tools we
expect. They run on every PR with no API keys.

## What lives in mcp-evals

- The YAML task fixtures (`tasks/*.yaml`).
- The MCP client + model adapters.
- The judge + scorer + reporter.
- The cross-model scorecards.

## Running the full eval against a local dev MCP

1. In this repo, start the server with `DEV_MODE_API_KEY` set — see the
   main README's "Local development with a personal API key" section.
2. In the sibling `mcp-evals/` checkout, set
   `FR_MCP_URL=http://localhost:8000/mcp` and any non-empty
   `FR_MCP_TOKEN` (dev mode bypasses JWT validation, so the token value
   does not matter — the harness's MCP client just needs to send the
   header):

   ```bash
   cd ../mcp-evals
   FR_MCP_URL=http://localhost:8000/mcp \
   FR_MCP_TOKEN=dev-mode-bypass \
   python run_eval.py --models claude --runs 3
   ```

## Adding fixtures for a new Prompt or tool

Open a PR against `financial-reports/mcp-evals`, not this repo. Drop a
YAML file into `tasks/`. See `tasks/core.yaml` for the field reference
(`id`, `prompt`, `domain`, `expected_tools`, `forbidden_tools`,
`assert_contains`, `success_rubric`).
