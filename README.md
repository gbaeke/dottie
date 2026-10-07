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
with Docker sandboxes and on Azure with Container Apps Sandboxes (a preview service). Sign-in (WorkOS) makes it multi-user
and is off by default: without it, restrict access (`ALLOWED_IPS`) when you deploy.

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
- **The runner** (`engine/runner.py`) is one waking: claim the mail, run the
  [Deep Agent](https://docs.langchain.com/oss/python/deepagents/overview), write what it does to the activity feed,
  deliver the answer, stop the sandbox. Where the agent loop runs depends on `AGENT_MODE` (below).
- **Memory is a wiki** (`engine/files.py`): markdown pages in PostgreSQL, mounted at `/wiki` in the agent's filesystem.
  `index.md` is always in its prompt (Deep Agents' `memory`), the rest it reads on demand and edits with the normal file
  tools. The user can read and edit the same pages. **Skills** are mounted read-only at `/skills`.
- **The sandbox** (`engine/sandboxes.py`): `none`, `docker` (a container per dottie, local) or `aca`
  ([Azure Container Apps Sandboxes](https://learn.microsoft.com/azure/container-apps/sandboxes-overview): stopped when
  the dottie sleeps, disk kept).
- **Tools** run in the app, never in the sandbox, so credentials stay out of reach of the agent: `messaging`
  (`list_dotties`, `send_message`, `tell_user`), `schedule`, `web` (`fetch_url`, public addresses only), `shell` (the
  sandbox), plus any **MCP servers** you attach to a dottie.
- **Dottie as an MCP server**: `/mcp/` exposes `list_dotties`, `ask_dottie` and `read_wiki` to other agents.
- Message loops are cut by a hop counter (`MAX_MESSAGE_DEPTH`) and a per-waking send limit.

## Where the agent runs: `AGENT_MODE`

| | `app` | `sandbox` |
|---|---|---|
| Agent loop (model calls, planning) | in the app process | inside the dottie's own sandbox (`src/dottie_runtime`) |
| `execute` and `/workspace` | in the sandbox, over `execute()` and file transfer | the machine the agent runs on |
| Conversation memory (checkpoints) | PostgreSQL | SQLite on the sandbox disk (rebuilt from the transcript in a new sandbox) |
| The app's job | everything | control plane: messages, clock, dispatcher, UI and API |
| Scaling | agent loops cost app CPU and memory | the app only waits; sandboxes scale on the platform |

In `sandbox` mode the dispatcher wakes the sandbox, installs the runtime on first use (about 30 seconds, kept on the
disk), starts it with a token for the run and waits. The runtime calls back to `/internal` (`api/internal.py`):
- `/context`: the prompt, input and tool list; `/llm/*`: the model, through the app, which adds the real credentials and
  keeps the dottie's own model name; `/tools/<name>`: the tools (messaging, schedules, web, MCP servers), which run in
  the app; `/wiki`, `/skills`, `/events` and `/finish`.
- The sandbox holds no database or model credentials. Its token is random per run and stops working when the run ends.
  Code the agent runs in its sandbox can read that token, and use it for what the run's own tools allow.
- **Logs and recovery.** The runtime logs what it does (run started and finished, tickets taken, failures, with times) to
  `/workspace/.dottie/last.log` in the sandbox, and a failed or timed-out run includes the tail of that log in the message the
  user sees. The app checks every 15 s that the runtime is alive and takes its tickets; a runtime that does not is restarted
  once, and a run is given up inside the sandbox when the app's time limit passes, so one hung run cannot block the ones behind
  it. The idle reaper never stops a sandbox whose dottie is being woken.
- On Azure a second app from the same image (`SERVE=internal`, `dottie-gate`) serves only `/internal`. It is open to the
  internet because sandboxes have no fixed address, while the main app keeps its IP rules.

## Users and sign-in

Sign-in is off until `WORKOS_CLIENT_ID` is set. Then the app is multi-user:

- **Sign-in** is [WorkOS AuthKit](https://workos.com/docs/authkit) with sealed sessions (`auth.py`). `ALLOWED_USERS` (comma
  separated emails) adds a list the app checks itself.
- **Everything belongs to a user**: dotties, and through them conversations, wiki, schedules, runs, the activity feed and the
  inbox. A user's own skills are private; the built-in skills are everyone's. Anything that is not yours answers
  `404 not found` (`api/access.py`), so nobody can tell what exists. `tests/test_multi_user.py` goes through every endpoint
  to prove it.
- **A dottie only knows the dotties of its own user**: `list_dotties` and `send_message` are scoped by owner. The activity
  stream only reports changes to your own dotties.
- **Limits**: `MAX_DOTTIES_PER_USER` (20). Sandboxes are labelled with the app, the dottie and the user.
- **Personal access tokens** (the Connect page, `/api/tokens`) let a user's other tools use their dotties over MCP: send the
  token as a Bearer token to `/mcp/`. Only a hash is stored, and the token is shown once.
- **Before sign-in existed**: what was made while the app ran without sign-in belongs to a local user. The first person who
  signs in takes it over; later users do not.

Set it up with the WorkOS CLI (`npm install -g workos`, then `workos auth login`):

```bash
# in .env: WORKOS_CLIENT_ID, WORKOS_API_KEY, SESSION_SECRET (openssl rand -base64 32); never in the chat
WORKOS_CLIENT_ID=client_... scripts/workos-uris.sh add http://localhost:8370   # redirect and sign-out addresses
```

On Azure: `WORKOS_CLIENT_ID=client_... WORKOS_API_KEY=sk_... scripts/azure-deploy.sh` stores them in the deployment state,
generates the session secret, and adds the app's address in WorkOS. `WORKOS_CLIENT_ID= scripts/azure-deploy.sh` turns
sign-in off again. The gateway app never needs them: it answers sandboxes with run tokens.

## Secrets and MCP servers

A dottie can use external MCP servers (search, docs, your own tools). Credentials for them live in the user's **secret
store**, never in a server's URL or config:

- **Store.** On the Connect page a user saves a value under a name (`tavily`). It is encrypted in the database (`SECRETS_KEY`)
  and **write-only**: the API shows a name and the last characters, and never gives the value back. A secret that an MCP
  server uses cannot be deleted until it is removed there. Secrets belong to a user.
- **Use.** A server has a `url`, `headers` and `query` parameters. Any value may contain `{{secret:NAME}}`, which the app
  fills in when it connects (`engine/mcp.py`), so the sandbox never sees it. A header or query parameter that looks like a
  credential (key, token, secret, auth, ...) or a password in the URL is refused unless it is a reference.
  Example for [Tavily](https://mcpservers.org/servers/tavily-mcp-server): url `https://mcp.tavily.com/mcp/`, header
  `Authorization: Bearer {{secret:tavily}}`.
- **Check.** "Test connection" in the editor connects like a dottie would and lists the tools. A server that cannot be reached
  or lacks a secret shows up as a problem in the dottie's activity feed.
- **Earlier configs.** A key saved inside a URL before secrets existed is moved into the owner's store at startup.
- **The key.** `SECRETS_KEY` (made for you locally; on Azure the deploy script makes it once and keeps it in
  `.azure/<resource group>.env`, so back that file up). Changing it makes stored secrets unreadable. Both Azure apps get it,
  because in sandbox mode the tools run in the gateway. The cipher sits in `engine/secrets.py`; a key held in Key Vault would
  replace only that class.

## Use dotties from other agents (MCP)

The app serves MCP over streamable HTTP at `/mcp/` (with sign-in on, send a personal access token as a Bearer token). Tools: `list_dotties`, `ask_dottie` (sends a message, waits for the
answer, and returns a conversation id when the dottie is still working) and `read_wiki`. Example client entry:

```json
{ "dottie": { "type": "http", "url": "http://localhost:8370/mcp/" } }
```

The other direction works too: attach any MCP server to a dottie in its settings and its tools join the dottie's own.
For example `https://learn.microsoft.com/api/mcp` gives it Microsoft Learn search.

## Run it

Needs [uv](https://docs.astral.sh/uv/), Node.js 24+ and Docker (for PostgreSQL and the dotties' sandboxes).

```bash
scripts/run-local.sh        # http://localhost:8370
```

Settings live in `.env` (created from `.env.example` on the first run). To let dotties think, set `LLM_BASE_URL`,
`LLM_API_KEY` and `LLM_MODEL` (an Azure Foundry OpenAI v1 endpoint, or any OpenAI-compatible gateway). Without a model
the app runs and tells you why a dottie cannot answer. `SANDBOX_BACKEND=docker` gives dotties with the `shell` toolkit a
container each (`none` for no shell).

### Settings

All settings are environment variables, listed with comments in `.env.example`.

| Setting | Purpose |
|---|---|
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | The model. An empty key on an Azure endpoint uses the managed identity. |
| `AGENT_MODE` | `app` or `sandbox`: where the agent loop runs. |
| `SERVE`, `GATEWAY_URL` | `internal` serves only the sandbox API; `GATEWAY_URL` is how a sandbox reaches it. |
| `SANDBOX_BACKEND` | `none`, `docker` or `aca`. |
| `SANDBOX_IMAGE` | Docker sandbox image (default `python:3.14-slim`). |
| `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `SANDBOX_GROUP`, `SANDBOX_REGION` | Where the `aca` backend finds its sandbox group. |
| `USER_TIMEZONE` | What "now" means to the dotties. |
| `MAX_MESSAGE_DEPTH`, `RUN_TIMEOUT_SECONDS`, `MAX_WORKERS` | Limits on message hops, one waking, and dotties awake at once. |

## Project layout

```
src/dottie/engine/   bus, scheduler, dispatcher, runner, agent, tools, files (wiki and skills), sandboxes
src/dottie/api/      one router per area: dotties, chat, wiki, schedules, skills, activity, system
src/dottie/mcp_server.py   Dottie as an MCP server
src/dottie_runtime/  the agent runtime that runs inside a sandbox (shares nothing with the app but HTTP)
frontend/            React, Vite, Tailwind; the API client is generated from the OpenAPI schema
infra/               Bicep for Azure; scripts/ has azure-up, azure-deploy and azure-down
tests/               pytest against a real PostgreSQL, with a scripted fake model
```

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

`azure-up.sh` also creates the sandbox group with a direct ARM call and grants the app's identity the "Container Apps
SandboxGroup Data Owner" role, because ARM preflight validation rejects that preview resource type in templates. If the
Container Apps environment fails with a capacity error in your region, set `APP_LOCATION` to another region: only the
environment and the app move, the data resources stay.

In `app` mode a dottie's sandbox starts only when the agent first runs a command or uses `/workspace`. In `sandbox` mode it
starts on every waking, because the agent lives there. After a run it stays running for `SANDBOX_IDLE_SECONDS` (default
120), so a follow-up message finds it warm; the engine stops it once the dottie's last run ended that long ago. A chat answer that needs no computer never resumes it, and an idle dottie costs nothing for compute. Its disk stays.

`main.bicep` creates PostgreSQL (Entra sign-in only), an Azure AI Services account with a model deployment (no key: the
app's managed identity signs in), a Container Apps **sandbox group**, a registry and the environment. The app runs with
one replica that is **always on**: the clock and the dispatcher live in it. Its dotties can use a
shell and the web, so protect the app: turn on sign-in (see Users and sign-in; `ALLOWED_USERS` lists who may enter) and/or
set `ALLOWED_IPS` (above) so only your network reaches it.

PostgreSQL accepts Entra sign-in only; as the deployer you are an admin too:
`PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv) psql "host=<server> user=<you@domain> dbname=dottie sslmode=require"`.
