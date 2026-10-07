"""Dottie as an MCP server: the tools work through the HTTP endpoint other agents would use."""

import json
import threading

from langchain_core.messages import AIMessage

from .test_dotties import make

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def call(client, tool: str, **arguments) -> str:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    res = client.post("/mcp/", content=json.dumps(body), headers=HEADERS)
    assert res.status_code == 200, res.text
    data = next(line for line in res.text.splitlines() if line.startswith("data:")).removeprefix("data:")
    result = json.loads(data)["result"]
    return "".join(part["text"] for part in result["content"])


def test_list_and_read_wiki(client):
    make(client, name="Ada", role="Chief of staff")
    assert "ada: Ada, Chief of staff" in call(client, "list_dotties")
    assert "Ada's wiki" in call(client, "read_wiki", dottie="ada")
    assert "No page" in call(client, "read_wiki", dottie="ada", path="nope.md")


def test_ask_a_dottie_wakes_it_and_returns_the_answer(client, scripts):
    make(client, name="Ada")
    scripts["ada"] = [AIMessage("Forty-two.")]
    engine = client.app.state.engine
    stop = threading.Event()

    def keep_waking():  # what the running engine does in the app
        while not stop.wait(0.2):
            engine.tick()

    worker = threading.Thread(target=keep_waking, daemon=True)
    worker.start()
    try:
        assert call(client, "ask_dottie", dottie="ada", message="What is the answer?", wait_seconds=30) == "Forty-two."
    finally:
        stop.set()
        worker.join()
        engine.wait_idle()
