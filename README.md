# Dottie

A small platform for **dotties**: persistent personal agents that sleep almost all the time. A dottie has its own
personality, skills, tools, long-term wiki and (optionally) a computer of its own. It wakes when you write to it, when
a schedule is due, or when another dottie sends it a message; it does the work, answers, and goes back to sleep.

Design inspired by OpenAI's *dots* and LangChain's wiki idea; see [docs/personal_ai_dot_architecture.docx](docs/personal_ai_dot_architecture.docx).
The principle: **persistent agent + durable memory + event-driven activation + replaceable sandbox**. The sandbox is the
dottie's computer, not the dottie.

## What you can do

- Create dotties in the web UI, each with a personality, skills, toolkits (messaging, schedule, web, shell) and optional MCP servers.
- Chat with a dottie. It wakes, works, answers and goes back to sleep.
- Give a dottie a schedule (cron or one-off) such as a daily briefing, or ask it to schedule itself.
- Let dotties write to each other. Each message wakes the recipient.
- Read and edit a dottie's wiki, and follow what it did in the activity feed.
- Talk to your dotties from other agents through the MCP endpoint.

## Status

An experiment to see how Azure Container Apps Sandboxes work as the foundation for always-on agents. It runs locally
with Docker sandboxes and on Azure with Container Apps Sandboxes (a preview service). The app has no sign-in, so
restrict access (`ALLOWED_IPS`) when you deploy it.

## How it fits together

```
 you / web UI / MCP clients ──┐
 schedules (the clock) ───────┼──► messages (PostgreSQL inbox) ──► dispatcher ──► Runner ──► Deep Agent
 other dotties ───────────────┘                                                              │  │  │
                                                              wiki + skills (PostgreSQL) ◄───┘  │  └─► sandbox (its computer)
                                                              checkpoints (PostgreSQL) ◄────────┘      docker | Azure Container Apps
```

- **Everything that wakes a dottie is a message** in one table (`messages`, `engine/bus.py`). Users, the scheduler and
  other dotties all use the same path. Swapping it for Azure Service Bus later touches only `post` and `claim`.
- **The clock** (`engine/scheduler.py`) turns due schedules (cron or one-off) into messages. A schedule keeps its own
  conversation, so each run builds on the last.
- **The dispatcher** (`engine/core.py`) wakes dotties that have mail. One process leads (a PostgreSQL advisory lock), so
  more replicas are safe.
- **The runner** (`engine/runner.py`) is one waking: claim the mail, start the sandbox, run the
  [Deep Agent](https://docs.langchain.com/oss/python/deepagents/overview), write what it does to the activity feed,
  deliver the answer, stop the sandbox.
- **Memory is a wiki** (`engine/files.py`): markdown pages in PostgreSQL, mounted at `/wiki` in the agent's filesystem.
  `index.md` is always in its prompt (Deep Agents' `memory`), the rest it reads on demand and edits with the normal file
  tools. The user can read and edit the same pages. **Skills** are mounted read-only at `/skills`.
- **The sandbox** (`engine/sandboxes.py`) implements Deep Agents' sandbox backend: `none`, `docker` (a container per
  dottie, local) or `aca` ([Azure Container Apps Sandboxes](https://learn.microsoft.com/azure/container-apps/sandboxes-overview):
  stopped when the dottie sleeps, disk kept). The agent's brain runs in the app; only its commands run in the sandbox.
- **Tools** run in the app, never in the sandbox, so credentials stay out of reach of the agent: `messaging`
  (`list_dotties`, `send_message`, `tell_user`), `schedule`, `web` (`fetch_url`, public addresses only), `shell` (the
  sandbox), plus any **MCP servers** you attach to a dottie.
- **Dottie as an MCP server**: `/mcp/` exposes `list_dotties`, `ask_dottie` and `read_wiki` to other agents.
- Message loops are cut by a hop counter (`MAX_MESSAGE_DEPTH`) and a per-waking send limit.

## Run it

Needs [uv](https://docs.astral.sh/uv/), Node.js 24+ and Docker (for PostgreSQL and the dotties' sandboxes).

```bash
scripts/run-local.sh        # http://localhost:8370
```

Settings live in `.env` (created from `.env.example` on the first run). To let dotties think, set `LLM_BASE_URL`,
`LLM_API_KEY` and `LLM_MODEL` (an Azure Foundry OpenAI v1 endpoint, or any OpenAI-compatible gateway). Without a model
the app runs and tells you why a dottie cannot answer. `SANDBOX_BACKEND=docker` gives dotties with the `shell` toolkit a
container each (`none` for no shell).

## Develop

```bash
scripts/run-local.sh --dev  # hot reload on http://localhost:5173
scripts/check.sh            # lint, types, tests: what CI runs
```

Tests never call a real model: a scripted fake model plays each dottie (`tests/conftest.py`). API docs:
http://localhost:8370/api/docs

## Deploy to Azure

Needs `az` (logged in: `az login`) and Docker.

```bash
ALLOWED_IPS=<your public ip>/32 scripts/azure-up.sh   # once, and when infra/main.bicep changes: infrastructure, then app
scripts/azure-deploy.sh                               # every new version: build and push the image, update only the app
scripts/azure-down.sh                                 # remove everything
```

`main.bicep` creates PostgreSQL (Entra sign-in only), an Azure AI Services account with a model deployment (no key: the
app's managed identity signs in), a Container Apps **sandbox group**, a registry and the environment. The app runs with
one replica that is **always on**: the clock and the dispatcher live in it. The app has **no sign-in**, and its dotties
can use a shell and the web: set `ALLOWED_IPS` (above) so only you reach it.

PostgreSQL accepts Entra sign-in only; as the deployer you are an admin too:
`PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv) psql "host=<server> user=<you@domain> dbname=dottie sslmode=require"`.
