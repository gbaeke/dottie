"""Generates docs/diagrams/dottie.drawio (two tabs): the Azure architecture, and one waking of a dottie.

    python3 docs/diagrams/dottie.py [out.drawio]

Needs the drawio-diagram skill's `drawio_kit.py` (set DRAWIO_KIT to its folder, or it is looked for in the Claude plugin
cache). Render to PNG to check it with the skill's `render.py`.
"""

import os
import sys
from itertools import pairwise
from pathlib import Path

CACHE = ".claude/plugins/cache/*/drawio-diagram/*/skills/drawio-diagram/scripts"
sys.path.insert(0, os.environ.get("DRAWIO_KIT") or next(iter(sorted(Path.home().glob(CACHE))), "").__str__())
from drawio_kit import Page, mono, pill, write_drawio  # noqa: E402

ORANGE, VIOLET, TEAL, AMBER, GREEN, BLUE = "#EA580C", "#7C3AED", "#0D9488", "#D97706", "#16A34A", "#2563EB"
RIGHT = "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"  # a straight edge from one card's right side to the next one's left
SMALL = "endSize=5;strokeWidth=1.2;"


def architecture() -> Page:
    p = Page("arch", "Architecture on Azure", 1680, 860)
    p.title(
        40,
        22,
        1000,
        "Dottie · architecture on Azure",
        "The agent loop runs in each dottie's own sandbox · the app is the control plane · one image, two apps",
    )
    legend = [("blue", "Clients"), ("violet", "Container Apps"), ("orange", "Sandboxes"), ("green", "Model")]
    legend += [("amber", "Data"), ("pink", "Identity"), ("slate", "Registry"), ("teal", "Logs")]
    p.legend(1040, 28, legend, per_row=4, col_w=150)

    # clients, outside the resource group
    users = p.group(40, 230, 150, 300, "blue", "Clients")
    browser = p.icon(users, 47, 50, "browser", 56)
    p.text(10, 112, 130, 34, "Browser<br>web UI", users, size=11, align="center")
    mcp = p.card(users, 10, 160, 130, 120, "blue", "MCP client", f"Claude Code, other agents<br>{mono('/mcp/')}")

    where = "apps in northeurope · data, model, sandboxes in swedencentral"
    rg = p.group(230, 110, 1400, 710, "azure", "rg-dottie", where, icon="resource_group")

    # --- Container Apps: the control plane ---
    cae = p.group(20, 55, 340, 400, "violet", "cae-&lt;suffix&gt;", "Container Apps env", rg, icon="container_app_env")
    app_body = (
        f"{pill('IP rule', 'azure')} UI · API · {mono('/mcp/')}<br>message inbox, clock, dispatcher<br>"
        f"1 vCPU · 2 Gi · exactly 1 replica<br>{mono('AGENT_MODE=sandbox')}"
    )
    tag = mono("dottie:&lt;tag&gt;")
    app = p.icard(cae, 15, 55, 310, 150, "violet", "container_app", "dottie", tag, app_body, isz=32)
    gate_body = (
        f"{pill('internet', 'warn')} {mono('SERVE=internal')}<br>only {mono('/internal')}: model, tools, wiki<br>"
        "a run token on every call<br>0.5 vCPU · 1 Gi · 1-5 replicas"
    )
    same = mono("same image")
    gate = p.icard(cae, 15, 225, 310, 150, "violet", "container_app", "dottie-gate", same, gate_body, isz=32)

    # --- Sandboxes: where the agents run ---
    sbx = p.group(
        400, 55, 340, 400, "orange", "sbg-&lt;suffix&gt;", "Sandboxes (preview)", rg, icon="container_instances"
    )
    box_body = (
        f"<b>dottie_runtime</b> in {mono('/opt/dottie')}<br>Deep Agent loop (model via the app)<br>"
        f"{mono('execute')} and {mono('/workspace')} are local<br>memory: SQLite in {mono('/workspace/.dottie')}<br>"
        "installs itself on first wake (~30 s)<br>egress policy applies"
    )
    title = "Sandbox · one per dottie"
    box = p.icard(sbx, 15, 55, 310, 320, "orange", "container_instances", title, "Ubuntu microVM", box_body, isz=32)
    names = [("stopped", False), ("running", True), ("warm 120 s", False)]
    states = [p.node(box, 12 + i * 100, 262, 90, 34, "orange", n, solid=solid) for i, (n, solid) in enumerate(names)]
    p.edge(states[0], states[1], "", RIGHT + SMALL, parent=box, color=ORANGE)
    p.edge(states[1], states[2], "", RIGHT + SMALL, parent=box, color=ORANGE)

    # --- Model ---
    fnd = p.group(800, 55, 270, 215, "green", "ais-&lt;suffix&gt;", "AI Services", rg, icon="foundry")
    model_body = f"Responses API<br>reached only through the gateway<br>no key: {pill('managed identity', 'azure')}"
    model = p.icard(
        fnd, 15, 50, 240, 150, "green", "openai", "gpt-6-luna", "GlobalStandard · 50K TPM", model_body, isz=28
    )

    # --- Registry, identity ---
    reg = p.group(800, 290, 270, 165, "slate", "acr&lt;suffix&gt;", "Registry", rg, icon="container_registry")
    reg_body = f"{tag} also carries<br>{mono('dottie_runtime')}, which the app<br>copies into the sandboxes"
    p.card(reg, 15, 50, 240, 100, "slate", "one image, two apps", reg_body)
    ident = p.group(1110, 55, 270, 400, "pink", "id-&lt;suffix&gt;", "user-assigned", rg, icon="managed_identity")
    roles = (
        "<b>AcrPull</b><br>pull the image<br><br><b>Cognitive Services OpenAI User</b><br>call the model<br><br>"
        "<b>SandboxGroup Data Owner</b><br>create and drive sandboxes<br><br><b>PostgreSQL Entra admin</b><br>"
        "run migrations, read and write<br><br>no passwords, no keys"
    )
    p.icard(ident, 15, 50, 240, 330, "pink", "managed_identity", "One identity", "shared by both apps", roles, isz=32)

    # --- bottom row: data, logs, guardrails ---
    pg = "PostgreSQL Flexible · Entra only"
    data = p.group(20, 495, 720, 195, "amber", "pg-&lt;suffix&gt;", pg, rg, icon="postgres")
    control = (
        f"{mono('messages')}: the inbox that wakes dotties<br>{mono('conversations')}, {mono('runs')} (+ token)<br>"
        f"{mono('events')}: the activity feed<br>{mono('schedules')}: cron and one-off"
    )
    db = p.card(data, 15, 50, 335, 120, "amber", "Control plane", control)
    memory = (
        f"{mono('wiki_pages')}: each dottie's long-term wiki<br>{mono('skills')}: assigned per dottie<br>"
        f"LangGraph checkpoints in {mono('app')} mode<br>(in {mono('sandbox')} mode: SQLite on the sandbox disk)"
    )
    p.card(data, 365, 50, 340, 120, "amber", "Memory", memory)
    logs = p.group(800, 495, 270, 195, "teal", "log-&lt;suffix&gt;", "Log Analytics", rg, icon="log_analytics")
    log_body = f"both apps log JSON<br>query by {mono('request_id')}<br>run id and dottie in the activity feed"
    p.card(logs, 15, 50, 240, 120, "teal", "container logs", log_body)
    guard = p.group(1110, 495, 270, 195, "cyan", "Guardrails", parent=rg)
    sections = [
        ("Sandbox", ["run token only", "no database or model key"]),
        ("Limits", ["5 message hops", "900 s per run"]),
    ]
    p.checklist(guard, 15, 46, 240, sections, color="cyan", line=14)

    # --- edges: waypoints are absolute page coordinates ---
    p.edge(browser, app, "HTTPS", "exitX=1;exitY=0.5;entryX=0;entryY=0.3;", color=BLUE)
    p.edge(mcp, app, "MCP", "exitX=1;exitY=0.5;entryX=0;entryY=0.7;", color=BLUE)
    p.edge(app, box, "wake", "exitX=1;exitY=0.5;entryX=0;entryY=0.234;", color=ORANGE)
    p.edge(box, gate, "callbacks", "exitX=0;exitY=0.766;entryX=1;entryY=0.5;", color=ORANGE)
    to_model = [(528, 585), (1000, 585), (1000, 290)]
    p.edge(
        gate,
        model,
        "model calls",
        "exitX=0.85;exitY=1;entryX=0;entryY=0.5;",
        points=to_model,
        color=GREEN,
        label_x=-0.4,
    )
    p.edge(gate, db, "wiki · tools · events", "exitX=0.4;exitY=1;entryX=0.37;entryY=0;", color=AMBER)
    sql = "exitX=0;exitY=0.85;entryX=0;entryY=0.167;"
    p.edge(app, db, "SQL", sql, points=[(257, 347), (257, 675)], color=AMBER, label_x=0.5)
    return p


def waking() -> Page:
    p = Page("flow", "One waking", 1700, 820)
    subtitle = "A message wakes a dottie; its agent runs in its sandbox and calls back; the app settles the run"
    p.title(40, 22, 1000, "Dottie · one waking", subtitle)
    p.legend(
        1180, 30, [("violet", "In the app"), ("orange", "In the sandbox"), ("teal", "Settling")], per_row=3, col_w=140
    )

    # lane 1: the app wakes the dottie
    l1 = p.group(40, 110, 1100, 205, "violet", "1 · The app wakes the dottie", f"{mono('engine/')} · control plane")
    first = [
        (
            "A message arrives",
            f"From you (UI, MCP), the clock or another dottie.<br>One row in {mono('messages')}, status "
            "<b>pending</b>.",
        ),
        (
            "The dispatcher claims it",
            f"Leader lock in PostgreSQL.<br>{mono('FOR UPDATE SKIP LOCKED')}, one run per dottie at a time.",
        ),
        ("A run starts", "A run row with a random token.<br>The messages become the run's input."),
        (
            "The sandbox wakes",
            "Resume it, or create it.<br>First time: install the runtime (~30 s).<br>"
            f"Start {mono('python -m dottie_runtime')} with the token.",
        ),
    ]
    s = [p.stage(l1, 15 + i * 270, 50, 245, 140, "violet", 1 + i, t, b) for i, (t, b) in enumerate(first)]
    for a, b in pairwise(s):
        p.edge(a, b, "", RIGHT, color=VIOLET)

    # lane 2: the agent in the sandbox
    l2 = p.group(40, 345, 1100, 215, "orange", "2 · In the sandbox")
    second = [
        ("Get the context", f"{mono('GET /internal/context')}: prompt, input, conversation so far, tool list."),
        ("Think", f"Deep Agent loop. Model calls go to {mono('/internal/llm')}: the app adds the credentials."),
        (
            "Act",
            f"Shell and {mono('/workspace')} are local. Wiki, skills and tools (messaging, schedules, web, MCP) "
            f"go through {mono('/internal')}.",
        ),
        ("Report", f"Tool calls and wiki edits stream to {mono('/internal/events')}: the activity feed."),
        ("Finish", f"{mono('POST /internal/finish')} with the answer."),
    ]
    a = [p.stage(l2, 15 + i * 215, 50, 195, 150, "orange", 5 + i, t, b) for i, (t, b) in enumerate(second)]
    for x, y in pairwise(a):
        p.edge(x, y, "", RIGHT, color=ORANGE)

    # lane 3: the app settles the run
    l3 = p.group(40, 590, 1100, 185, "teal", "3 · Back in the app")
    third = [
        (
            "The answer is delivered",
            "Reply posted to the chat or inbox, messages marked done, token revoked.<br>"
            f"A dottie's answer to a dottie is dropped: it uses {mono('send_message')}.",
        ),
        (
            "A warm window",
            f"The sandbox keeps running for {mono('SANDBOX_IDLE_SECONDS')} (120).<br>A follow-up skips the resume.",
        ),
        (
            "The reaper stops it",
            f"No run for 120 s: {mono('Engine.reap_idle')} stops the sandbox.<br>Its disk and memory file stay.",
        ),
    ]
    t = [p.stage(l3, 15 + i * 360, 50, 340, 120, "teal", 10 + i, h, b) for i, (h, b) in enumerate(third)]
    for x, y in pairwise(t):
        p.edge(x, y, "", RIGHT, color=TEAL)

    # between the lanes (waypoints are absolute; they enter to the right of the lane titles)
    down = "exitX=0.5;exitY=1;entryX={};entryY=0;"
    p.edge(
        s[3],
        a[0],
        "start runtime, with token",
        down.format(0.923),
        points=[(987, 330), (235, 330)],
        color=VIOLET,
        label_x=0.1,
    )
    p.edge(
        a[4],
        t[0],
        "dottie reports its end",
        down.format(0.72),
        points=[(1012, 575), (300, 575)],
        color=ORANGE,
        label_x=0.1,
    )

    panel = p.group(1180, 110, 480, 440, "cyan", "Guardrails and memory")
    sections = [
        (
            "Credentials",
            [
                "The sandbox holds a run token, nothing else",
                "The model identity stays in the app",
                "Tool credentials (MCP servers) stay in the app",
                "The token stops working when the run ends",
            ],
        ),
        (
            "Limits",
            [
                f"Message hops: 5 ({mono('MAX_MESSAGE_DEPTH')})",
                "Sends per waking: 5",
                f"Run time: 900 s ({mono('RUN_TIMEOUT_SECONDS')})",
                f"{mono('fetch_url')}: public addresses only",
            ],
        ),
        (
            "When it fails",
            [
                "A runtime that dies is noticed within 15 s",
                "An install failure shows the log tail",
                "The user gets the error as a system message",
            ],
        ),
        (
            "Memory",
            [
                "Wiki and skills: PostgreSQL, read and written over HTTP",
                "Conversation: SQLite on the sandbox disk",
                "A new sandbox rebuilds it from the transcript",
            ],
        ),
    ]
    p.checklist(panel, 15, 50, 450, sections, color="cyan", line=17)
    return p


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("dottie.drawio"))
    write_drawio(out, [architecture(), waking()])
