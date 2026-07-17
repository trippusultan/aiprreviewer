# AI-Powered GitHub PR Code Reviewer

![CI](https://github.com/trippusultan/aiprreviewer/actions/workflows/ci.yml/badge.svg)

An event-driven, multi-agent code review system. When a developer opens / updates
a pull request, a GitHub webhook triggers a pipeline that fetches the diff and runs
**four parallel AI review agents** (Static Analysis, Security, Architecture,
Style) orchestrated by **LangGraph**, merges and de-duplicates their findings, and
posts inline comments + a summary back to the PR. A self-improving **Learner**
service extracts recurring patterns from merged PRs so future reviews get smarter.

> Architecture reference: "AI-Powered Code Review Pipeline" diagram
> (https://roadmap.sh/projects/ai-powered-code-review-pipeline). Built as the
> roadmap.sh *AI-Powered Code Review Pipeline* project solution.

```mermaid
flowchart LR
    Dev([Developer]) -->|open/update PR| GH[(GitHub)]
    GH -->|webhook + HMAC| GW[Gateway\nHMAC verify]
    GW --> WH[Webhook\nparse / dedupe / store]
    WH -->|enqueue| RD[(Redis)]
    RD -->|task| CW[Celery Worker\nprocess_pr]
    CW --> OR[Orchestrator\nfetch diff + load patterns]
    OR --> LG{{LangGraph}}
    LG --> S0[Static Agent]
    LG --> S1[Security Agent\nOWASP]
    LG --> S2[Architecture Agent]
    LG --> S3[Style Agent]
    S0 & S1 & S2 & S3 --> MR[Merge + de-dupe]
    MR --> PG[(PostgreSQL\nreviews + learned_patterns)]
    MR --> RV[Reviewer\nGitHub App / token]
    RV -->|inline comments + summary| GH
    GH -->|closed + merged| WH
    WH --> LN[Learner\nextract patterns]
    LN --> PG
    OR -. patterns .-> LG

    subgraph Observability
        PR[Prometheus] --> GR[Grafana]
    end
    GW & WH & OR & RV & LN -. /metrics .-> PR
```

---

## What you get

| Box in diagram | Implementation |
|---|---|
| Gateway Service (FastAPI) | `gateway/` — HMAC verify → reject fakes → forward verified |
| Webhook Processing | `webhook/` — parse PR, dedupe by SHA, store metadata |
| Queue & Worker | `worker/` — Celery + Redis (ElastiCache) |
| Orchestrator | `orchestrator/` — fetch diff, load repo patterns, run LangGraph |
| AI Agents (parallel) | `engine/` — 4 agents + merge/dedup |
| Reviewer Service | `reviewer/` — GitHub App JWT → installation token → post comments |
| Learner Pipeline | `learner/` — extract frequent issues → repo patterns |
| PostgreSQL RDS | `common/db.py` (SQLAlchemy async, sqlite+aiosqlite offline) |
| Monitoring | Prometheus + Grafana + Langfuse |
| DevOps CI/CD | `.github/workflows/ci.yml` + Docker / EKS-ready |

---

## Run it offline in 2 minutes (no API key, no Redis, no Postgres)

```bash
uv venv .venv && . .venv/Scripts/activate      # or: source .venv/bin/activate
uv pip install . pytest pytest-asyncio httpx
RUN_OFFLINE=true pytest -q                     # full suite: engine, security, services, integration
```

Launch the five services locally (StubLLM + sqlite):

```bash
./run_local.sh        # or run_local.bat on Windows
```

Then simulate a review:

```bash
curl -X POST http://localhost:8002/review \
  -H 'Content-Type: application/json' \
  -d '{"action":"opened","pull_request":{"number":1,"head":{"sha":"abc"},
       "base":{"sha":"def"},"title":"x","body":"","files":[]},
       "repository":{"full_name":"owner/repo"}}'
```

## Real deployment

1. `cp .env.example .env`. Configure the LLM via `LLM_PROVIDER` + `LLM_API_KEY`
   + `LLM_BASE_URL` + `LLM_MODEL` (provider-agnostic — OpenAI, OpenRouter, Groq,
   DeepSeek, Ollama, vLLM, Azure OpenAI, or Anthropic Claude). Then set
   `GITHUB_WEBHOOK_SECRET`, `GITHUB_TOKEN` (or full GitHub App credentials),
   `DATABASE_URL` (`postgresql+asyncpg://...`).
2. `docker compose up --build` (Redis + Postgres + 5 services + worker +
   Prometheus + Grafana).
3. In your GitHub repo: **Settings → Webhooks → Add** pointing at the Gateway
   `/webhook` URL, content-type `application/json`, secret = `GITHUB_WEBHOOK_SECRET`,
   events = *Pull requests*.

---

## Project layout

```
aiprreviewer/
├── common/        config, models, llm (provider-agnostic: OpenAI-compatible,
│                  Anthropic, or offline StubLLM), security (HMAC), github client,
│                  db, observability
├── engine/        LangGraph multi-agent review graph + prompts
├── gateway/       entry point: verify → forward
├── webhook/       parse → dedupe → store → enqueue
├── orchestrator/  fetch diff → load patterns → run engine → reviewer
├── reviewer/      GitHub App auth → post comments + summary
├── learner/       extract patterns from merged PRs
├── worker/        Celery task = process_pr
├── tests/         pytest (engine e2e, hmac, parsing, service health)
├── docker-compose.yml / Dockerfile / prometheus.yml
└── .github/workflows/ci.yml
```

## Notes
- The LLM layer (`common/llm.py`) is **provider-agnostic**: `LLM_PROVIDER` selects
  an OpenAI-compatible endpoint (OpenAI, OpenRouter, Groq, DeepSeek, Ollama, vLLM,
  Azure) or native **Anthropic Claude**. With `RUN_OFFLINE=true` (or no
  key/endpoint) it falls back to the deterministic `StubLLM`.
- The **Reviewer** posts each inline comment individually to GitHub's
  `POST /repos/{owner}/{repo}/pulls/{n}/comments` endpoint (it takes one comment,
  not a batch) and posts a summary review. Line-less findings are folded into the
  summary. Posting requires a `GITHUB_TOKEN` (or GitHub App installation token);
  without one the `/post` response reports `summary_posted: false` rather than a
  false success.
- Security agent is aligned with the **OWASP Top 10**.
- Built and verified on the device of trippusultan (github.com/trippusultan).

## Live end-to-end test (real GitHub)

`tests/test_live_e2e_ephemeral.py` creates a throwaway public repo, opens a PR
seeded with intentional issues (hard-coded secret, bare `except`, `global`
mutation), runs the real review pipeline + Reviewer, asserts findings land on
the PR, then **deletes the repo** (even on failure). It needs a GitHub PAT
(`repo` scope) + optionally an LLM key, supplied via env / CI secrets:

| var | purpose |
|-----|---------|
| `LIVE_E2E_TOKEN` | GitHub PAT (repo scope) — required to run |
| `LIVE_E2E_LLM_KEY` | real LLM key; if absent the engine uses `StubLLM` |
| `LIVE_E2E_LLM_BASE` / `LIVE_E2E_LLM_MODEL` | OpenAI-compatible endpoint + model |

Run locally:
```bash
LIVE_E2E_TOKEN=ghp_xxx LIVE_E2E_LLM_KEY=sk-xxx \
RUN_OFFLINE=false pytest tests/test_live_e2e_ephemeral.py -q -s
```

In CI it is a separate `live-e2e` job that runs **only on manual
`workflow_dispatch`** with the `LIVE_E2E_TOKEN` / `LIVE_E2E_LLM_KEY` repository
secrets configured — it never runs on normal push/PR, so the default suite
stays offline-green. `tests/test_live_e2e_mock.py` verifies the test's GitHub
orchestration + teardown against a local mock API (no token needed).
