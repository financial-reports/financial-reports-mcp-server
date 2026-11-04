# OPERATIONS.md

How this MCP server actually reaches production, who can deploy it, and which lines of
this repo other repositories depend on by literal string match.

This file is deliberately **identifier-free**: it names no project ids, regions, service
names, registry paths, service accounts, cache instances, or internal addresses. Those
live in the internal runbook (see [Internal runbook](#internal-runbook)). Everything here
uses shell variables you fill in from that runbook: `$PROJECT_ID`, `$REGION`, `$SERVICE`,
`$AR_REPO`, `$TAG`.

---

## TL;DR

| Question | Answer |
|---|---|
| What serves production? | **Google Cloud Run**, behind a Google **external Application Load Balancer** |
| Public endpoint | `https://mcp.financialfilings.com/mcp` |
| Where do images live? | **Google Artifact Registry** |
| Where does OAuth state live? | **Memorystore for Valkey 7.2**, wired in via `MCP_REDIS_URL` |
| Does merging to `main` deploy? | **No.** See [below](#-merging-to-main-does-not-ship) |
| Where is the deploy automation? | In the **private companion repo `financial-reports/web`**, not here |
| Access needed to deploy by hand | GCP **Cloud Run deploy** + **Artifact Registry write** (not Azure, not GitHub write) |
| How do I see what's live? | `curl -fsS https://mcp.financialfilings.com/health` |

The `/health` response carries the build stamp:

```bash
curl -fsS https://mcp.financialfilings.com/health
# {"status":"ok","service":"...","version":"<MCP_VERSION baked at image build>"}
```

`version` is the `MCP_VERSION` build arg from the image that produced the serving
revision. It is the only authoritative answer to "did my change ship?".

Historical note: production ran on **Azure Container Apps** until the 2026 migration to
Google Cloud Run (the Azure sponsorship was winding down). The Azure resources named in
older issues, PRs, and comments **no longer exist**. Where this repo's comments and tests
recount Azure-era incidents, the history is accurate and kept — those notes are marked
`(pre-GCP-migration)`.

---

## ⚠️ Merging to `main` does not ship

`.github/workflows/` **in this repo contains no workflow that deploys.** `ci.yml` lints,
regenerates, and tests; `fastmcp-3x-probe.yml`, `prod-probe.yml` and `snapshot-drift.yml`
probe and report. None of them builds an image and none of them deploys anything. A
reader who stops there reasonably concludes there is no deploy automation at all. That is
almost right, and the gap is the important part.

The build-and-deploy job lives in the **private companion repo**, at
`.github/workflows/generate_sdks.yml` in `financial-reports/web`. It holds a token for
this repo. It is **gated on a schema change**:

```yaml
if: steps.changed.outputs.schema_changed == 'true'
```

That guard is present on **every** build step and **every** deploy step in that job — not
just the SDK-publishing step. So the only thing that automatically ships this server is a
change to the upstream OpenAPI schema. When one happens, the pipeline:

1. regenerates and publishes the `financial_reports_generated_client` SDK wheel;
2. checks out **this** repo at `main`, patches it (see
   [The three literal-match anchors](#the-three-literal-match-anchors)), and builds the image;
3. deploys that image to Cloud Run;
4. pushes a `chore: bump financial_reports_generated_client to vX.Y.Z` commit back to this
   repo's `main`.

Read the consequence carefully:

> **An MCP-only change ships nothing.** Merge a fix to `main` here and production keeps
> serving the previous image indefinitely. It reaches prod only when (a) an unrelated
> upstream schema change happens to carry it along, or (b) somebody
> [hand-deploys](#hand-deploy). There is no third path.

Corollary for anyone writing a changelog, a release note, or an issue comment: "merged"
and "deployed" are independent facts here. Confirm the second with `/health`.

Also note the direction of the coupling. Those `chore: bump …` commits on `main` did not
come from a human in this repo; they are the deploy pipeline reporting back. Their
presence is evidence a deploy happened. Their *absence* over a long stretch means nothing
has shipped, however much has merged.

---

## The three literal-match anchors

Before building, the web repo's workflow **patches this repo's checkout with `sed`**, to
swap the published SDK pin for the freshly built wheel:

```bash
sed -i '/financial_reports_generated_client/d' requirements.txt
sed -i '/^COPY requirements\.txt/a COPY '"${WHL}"' /app/' Dockerfile
sed -i 's|uv pip install -r requirements.txt|uv pip install /app/'"${WHL}"' --no-cache-dir \&\& uv pip install -r requirements.txt|' Dockerfile
```

Every one of those three is a **literal string match against a line in this repo**. None
of them is a structural or semantic match. Rename or reflow any of them and the patch
silently changes meaning:

| # | The anchor | Where | If it stops matching |
|---|---|---|---|
| 1 | the line containing `financial_reports_generated_client` | `requirements.txt` | The published pin is not deleted, so the image gets **two SDK specifications** — the fresh wheel plus a conflicting published pin. Resolution order decides which wins. Best case a loud resolver conflict; worst case the wrong SDK. |
| 2 | a line **starting with** `COPY requirements.txt` | `Dockerfile` | The `COPY <wheel> /app/` line is never inserted, so the wheel is absent when the next step tries to install it. **The build fails loudly.** Annoying, but self-announcing. |
| 3 | the exact substring `uv pip install -r requirements.txt` | `Dockerfile` | The substitution **no-ops**. The build succeeds, the deploy succeeds, and the image installs the **old published SDK** instead of the newly built wheel. |

**Anchor 3 is the dangerous one.** It has no failure signal at all: green workflow, green
deploy, healthy `/health`, and a production image running an SDK that predates the schema
change that triggered the whole pipeline. Nothing surfaces until some caller hits a field
the deployed SDK does not know about.

Treat these three lines as **a public API of this repo**. Specifically:

- Keep the `financial_reports_generated_client` pin on its own line in `requirements.txt`.
- Keep `COPY requirements.txt` at the **start** of its line in the `Dockerfile` (no
  leading whitespace, no `COPY ./requirements.txt`, no folding it into a multi-source
  `COPY`).
- Keep the literal `uv pip install -r requirements.txt` intact — do not split it across
  lines, do not add flags between `install` and `-r`, do not switch to `uv sync`,
  `uv pip install --requirements`, `pip install -r`, or a `uv pip compile` step.

Switching to a lockfile (`uv.lock`, `requirements.lock`, pip-tools output), renaming
`requirements.txt`, or restructuring the install into multiple requirement files is
therefore a **two-repo change**: land the web-repo workflow update and this repo's change
together, or the next schema-triggered deploy ships the wrong SDK with no warning. Do not
do it as a "harmless cleanup" PR here.

---

## Hand-deploy

Use this when an MCP-only change needs to reach production, which is the normal case for
work in this repo.

**Access required:** GCP Cloud Run deploy + Artifact Registry write on the production
project. Notably *not* Azure (those resources are gone) and *not* GitHub write on this
repo — merging is neither necessary nor sufficient.

Fill the variables from the internal runbook:

```bash
PROJECT_ID=…      # production GCP project
REGION=…          # Cloud Run region
SERVICE=…         # Cloud Run service name
AR_REPO=…         # Artifact Registry repository name
TAG=…             # the version you are shipping, e.g. 1.5.12
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO/financial-reports-mcp:$TAG"
```

```bash
# 1. Authenticate Docker against Artifact Registry (once per machine/region).
gcloud auth login
gcloud config set project "$PROJECT_ID"
gcloud auth configure-docker "$REGION-docker.pkg.dev"

# 2. Build. --platform is REQUIRED on Apple Silicon: Cloud Run is amd64 only,
#    and an arm64 image pushes fine and then fails to start.
#    MCP_VERSION is what /health will report — set it to the tag you are shipping.
docker build --platform linux/amd64 --build-arg MCP_VERSION="$TAG" -t "$IMAGE" .

# 3. Push.
docker push "$IMAGE"

# 4. Deploy. This creates a new revision and, by default, sends all traffic to it.
gcloud run services update "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION" \
  --image "$IMAGE"

# 5. VERIFY. The reported version must equal $TAG. If it does not, traffic is
#    still on the old revision — do not declare the deploy done.
curl -fsS https://mcp.financialfilings.com/health
```

The image build runs the generator with `FR_PIN_SCHEMA=1`, so the tool surface comes from
the committed `scripts/openapi.snapshot.json` snapshot and cannot drift between your build
and CI's.

### Rollback

Cloud Run keeps previous revisions, so rollback is a traffic shift, not a rebuild:

```bash
# List revisions newest-first and pick the last known-good one.
gcloud run revisions list --service "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION"

# Send 100% of traffic back to it.
gcloud run services update-traffic "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION" \
  --to-revisions=<PREVIOUS>=100

# Confirm: /health should now report the previous version again.
curl -fsS https://mcp.financialfilings.com/health
```

**Revision naming.** Cloud Run revisions are `<service>-<nnnnn>-<hash>` — a zero-padded
counter plus a short suffix, e.g. `…-00123-abc`. The `<app>--<suffix>` form (double
hyphen, no counter/hash split) that appears in older issues and PRs is **Azure Container
Apps** naming and predates the migration; it is also where the stale "rev 0074"-style
references come from. If you see a `--` revision name, you are reading pre-migration
history.

---

## x402 pay-per-call endpoint (`/mcp-pay`)

Off unless `MCP_X402_ENABLED=1`. With it on, the same service also serves
`https://mcp.financialfilings.com/mcp-pay`: a second MCP server with **no sign-in**,
whose tools (the priced GET subset of the default surface, same names and parameters)
are paid per call in USDC under the x402 MCP transport. `/mcp` and its OAuth are
unchanged either way; with the flag off, the root mount is exactly the old `mcp_app`.

**What it does.** Each tool call is one keyless GET to `API_BASE_URL`. The API does all
the payment work, exactly as for a direct keyless REST call: it quotes (a 402 whose
`PAYMENT-REQUIRED` this server returns as an `isError` result with the PaymentRequired in
`structuredContent`), verifies the `_meta["x402/payment"]` the caller retries with (sent
up as `PAYMENT-SIGNATURE`), serves, settles, and its `PAYMENT-RESPONSE` comes back in
`_meta["x402/payment-response"]`. So there is one price table, the payment ledger is the
API's, and this service holds no payment keys. A paid call is never retried (that would
replay its nonce). The API must have x402 on (`X402_ENABLED`, not probe-only) or every
call answers 403.

**Enable:**

```bash
gcloud run services update "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --update-env-vars MCP_X402_ENABLED=1
```

**Disable:** the same with `MCP_X402_ENABLED=0` (or `--remove-env-vars MCP_X402_ENABLED`).

**Verify** (an unpaid call must come back as a PaymentRequired):

```bash
curl -sS https://mcp.financialfilings.com/mcp-pay \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"filing_types_list","arguments":{}}}'
# expect "isError":true and a structuredContent with "x402Version":2 and "accepts"
```

**Known limits (v1, by design):**

- **Who can pay.** Clients built on an x402 MCP client SDK (`x402` Python
  `x402.mcp.x402MCPSession`, `@x402/mcp` TypeScript, Go). Hosted assistants (claude.ai,
  ChatGPT, Cursor, Codex) are not known to sign x402 payments over MCP; untested.
- **The API sees this service's IP**, not the payer's. Every relayed payment is recorded
  with the country of the Cloud Run egress, and all relayed callers share the API's
  per-network x402 limits (`X402_ISSUE_PER_WIDE_IP_MIN` quotes and
  `X402_VERIFY_PER_WIDE_IP_MIN` verifies a minute per /24). Fixing either needs a
  trusted relay header on the API side.
- **No markdown re-read discount.** Each `filings_markdown_retrieve` window is a new
  payment (100k characters by default, 140k max), as on keyless REST.
- **No usage analytics.** `UsageAnalyticsMiddleware` is on the `/mcp` server only; the
  API's payment ledger is the record. Each relayed call logs one `x402 relay` line.

---

## Runtime facts that constrain the code

Several comments in `scripts/generate_mcp_tools.py` read oddly until you know how the
serving platform behaves. These are the load-bearing facts:

**Disk is ephemeral, and there are several instances.** Cloud Run gives each instance a
writable but throwaway filesystem, and scales the service to many instances with **no
session affinity** at the load balancer. Two consequences the code is built around:

- **`MCP_REDIS_URL` is not optional in production.** FastMCP's OAuth proxy otherwise
  falls back to a per-instance encrypted `DiskStore`. A dynamic client registration
  written on instance A is invisible to instance B, and every deploy wipes all of them —
  users get `invalid_client` and "reconnect the connector". The server pings Redis at boot
  and fails the revision if it is unreachable, deliberately.
- **`stateless_http=True` on the MCP transport is required**, not a preference. A stateful
  session keyed by `Mcp-Session-Id` and held in one instance's memory is unknown to the
  next instance the load balancer picks; the follow-up `POST /mcp` returns the
  spec-mandated "session not found" 404 and the client surfaces `McpSessionTerminated`.
  Do not switch it off without both a shared session store and load-balancer session
  affinity actually configured.

**Cloud Run ignores the Docker `HEALTHCHECK` instruction entirely.** It uses its own
`tcpSocket` startup probe against the container port instead. The `HEALTHCHECK` in the
`Dockerfile` therefore only ever runs under local `docker run` and `docker compose`
(including `docker-compose.test.yml`). Keep it — it is a real signal locally — but do not
reason about production readiness from it, and do not try to change prod probe behaviour
by editing it.

**Cloud Run injects no per-instance environment variable.** The only platform-provided env
vars are `K_SERVICE`, `K_REVISION`, `K_CONFIGURATION`, and `PORT` — and all four are
identical across every instance of a revision. There is no Cloud Run equivalent of Azure
Container Apps' `CONTAINER_APP_REPLICA_NAME`. And `socket.gethostname()` returns
`localhost` inside a Cloud Run container, so it is not a usable fallback either. Anything
that needs to tell instances apart in logs must synthesise its own per-process identity —
see `_instance_id()` in the generator.

**The instance metadata endpoint is reachable from inside the container.** That is
ordinary for a managed compute platform, and it is precisely why `_validate_webhook_url()`
blocks link-local/metadata addresses: without it, a subscriber could register a webhook
pointing at the metadata service and use this server as an SSRF relay to read instance
credentials. The Django backend does the authoritative check; the MCP-side block is
defence in depth. Do not relax it.

---

## Internal runbook

Concrete identifiers — project id and number, region, Cloud Run service and revision
names, Artifact Registry paths, deploy service accounts and Workload Identity Federation
providers, the Memorystore instance, load-balancer objects, Cognito pool/client ids, and
Secret Manager key names — are **not** in this public repo.

They live in the private `financial-reports/web` repo's `docs/OPERATIONS.md`, alongside
the `generate_sdks.yml` workflow that uses them and the operator runbook that points here
for the platform-level picture.

If you have a change that needs one of those values, you need access to that repo; do not
work around it by adding the value here.

## Official MCP Registry listing

The server is listed in the official MCP Registry as `com.financialfilings/mcp-server`
(`https://registry.modelcontextprotocol.io/v0.1/servers?search=financialfilings`). The entry is
`server.json` at the repo root. Merging or deploying does **not** update it; the registry only
changes when someone publishes. The namespace is proven by a DNS TXT record
(`v=MCPv1; k=ed25519; …`) on the `financialfilings.com` apex; the matching private key is a Secret Manager
secret (`$REGISTRY_KEY_SECRET`, named in the internal runbook). To publish a new version (versions are immutable, so bump
`version` in `server.json` first):

```bash
# mcp-publisher: https://github.com/modelcontextprotocol/registry/releases
# Ed25519 needs OpenSSL 3 (macOS: /opt/homebrew/opt/openssl@3/bin/openssl)
(
  umask 077                                   # key file is 0600, scoped to this subshell
  KEY="$(mktemp)"; trap 'rm -f "$KEY"' EXIT   # removed even if login/publish fails
  gcloud secrets versions access latest --project "$PROJECT_ID" --secret "$REGISTRY_KEY_SECRET" > "$KEY"
  PRIV="$(openssl pkey -in "$KEY" -noout -text | grep -A3 'priv:' | tail -n +2 | tr -d ' :\n')"
  mcp-publisher login dns --domain financialfilings.com --private-key "$PRIV" && mcp-publisher publish
)
mcp-publisher logout                          # drop the cached registry token
```

If the key is rotated, remove the old TXT record from the apex: the registry tries a stale record
first and fails.

Until 2026-10-10 the entry was published as `eu.financialreports/mcp-server`, proven by the same
key on the `financialreports.eu` apex. That entry is now `deprecated` with a message pointing here.
Managing it (for example restoring it) needs `login dns --domain financialreports.eu`, so the
TXT record on that apex stays.
