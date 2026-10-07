"""The whole loop through the HTTP API: a message wakes a dottie, it works, answers and sleeps again."""

from langchain_core.messages import AIMessage

from .test_dotties import make


def call(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call-{name}"}


def say(text: str) -> AIMessage:
    return AIMessage(text)


def use(*calls: dict) -> AIMessage:
    return AIMessage("", tool_calls=list(calls))


def wake_everyone(client) -> None:
    engine = client.app.state.engine
    engine.tick()
    engine.wait_idle()


def chat(client, dottie_id: int, text: str) -> str:
    conversation = client.post(f"/api/dotties/{dottie_id}/conversations", json={}).json()["id"]
    assert client.post(f"/api/conversations/{conversation}/messages", json={"body": text}).status_code == 201
    return conversation


def events(client, dottie_id: int) -> list[dict]:
    return client.get(f"/api/dotties/{dottie_id}/events").json()[::-1]


def test_a_message_wakes_the_dottie_and_it_answers(client, scripts):
    ada = make(client)
    scripts["ada"] = [say("Good morning!")]
    conversation = chat(client, ada["id"], "Hi Ada")
    assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "queued"

    wake_everyone(client)

    messages = client.get(f"/api/conversations/{conversation}/messages").json()
    assert [(m["sender_kind"], m["body"], m["status"]) for m in messages] == [
        ("user", "Hi Ada", "done"),
        ("dottie", "Good morning!", "done"),
    ]
    assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "sleeping"
    kinds = [e["kind"] for e in events(client, ada["id"])]
    assert kinds[0] == "wake" and kinds[-1] == "sleep"
    runs = client.get(f"/api/dotties/{ada['id']}/runs").json()
    assert [(r["status"], r["trigger"]) for r in runs] == [("done", "user")]
    # the reply is also in the user's inbox, unread, until the conversation is read
    assert client.get("/api/dotties").json()[0]["unread"] == 1
    client.post(f"/api/conversations/{conversation}/read")
    assert client.get("/api/dotties").json()[0]["unread"] == 0


def test_the_conversation_continues_across_wakings(client, scripts):
    ada = make(client)
    scripts["ada"] = [say("First."), say("Second.")]
    conversation = chat(client, ada["id"], "one")
    wake_everyone(client)
    client.post(f"/api/conversations/{conversation}/messages", json={"body": "two"})
    wake_everyone(client)
    bodies = [m["body"] for m in client.get(f"/api/conversations/{conversation}/messages").json()]
    assert bodies == ["one", "First.", "two", "Second."]


def test_the_dottie_keeps_what_it_learns_in_its_wiki(client, scripts):
    ada = make(client)
    scripts["ada"] = [
        use(call("edit_file", file_path="/wiki/user.md", old_string="Nothing yet.", new_string="Likes tea.")),
        use(call("write_file", file_path="/wiki/people/anna.md", content="# Anna\nColleague.")),
        say("Noted."),
    ]
    chat(client, ada["id"], "Remember that I like tea, and that Anna is a colleague.")
    wake_everyone(client)

    wiki = f"/api/dotties/{ada['id']}/wiki"
    assert "Likes tea." in client.get(f"{wiki}/user.md").json()["content"]
    assert client.get(f"{wiki}/people/anna.md").json()["updated_by"] == "dottie"
    wiki_events = [e["text"] for e in events(client, ada["id"]) if e["kind"] == "wiki"]
    assert wiki_events == ["Updated user.md", "Updated people/anna.md"]


def test_a_dottie_cannot_change_its_skills_or_use_a_shell_it_was_not_given(client, scripts):
    ada = make(client, tools=["messaging"])
    scripts["ada"] = [
        use(call("write_file", file_path="/skills/new/SKILL.md", content="x"), call("execute", command="ls")),
        say("Done."),
    ]
    chat(client, ada["id"], "Try things.")
    wake_everyone(client)
    results = [e["text"] for e in events(client, ada["id"]) if e["kind"] == "tool_result"]
    assert any("read-only" in r or "cannot be changed" in r for r in results)
    assert any("not available" in r for r in results)


def test_dotties_talk_through_the_message_layer(client, scripts):
    ada, rex = make(client, name="Ada"), make(client, name="Rex", role="Researcher")
    scripts["ada"] = [use(call("send_message", to="rex", message="Find the capital of Belgium.")), say("Asked Rex.")]
    scripts["rex"] = [say("It is Brussels.")]
    chat(client, ada["id"], "Ask Rex for the capital of Belgium.")

    wake_everyone(client)  # Ada wakes, writes to Rex, sleeps; Rex has mail now
    assert client.get(f"/api/dotties/{rex['id']}").json()["state"] == "queued"
    wake_everyone(client)  # Rex wakes

    traffic = client.get("/api/bus").json()
    assert [(t["message"]["sender_name"], t["recipient_name"], t["message"]["body"]) for t in traffic] == [
        ("Ada", "Rex", "Find the capital of Belgium.")
    ]
    rex_runs = client.get(f"/api/dotties/{rex['id']}/runs").json()
    assert [(r["trigger"], r["status"]) for r in rex_runs] == [("dottie", "done")]
    # a dottie's answer to a dottie is not delivered to the user's inbox
    assert client.get("/api/inbox").json()[0]["dottie_name"] == "Ada"
    assert len(client.get("/api/inbox").json()) == 1
    assert any(e["kind"] == "sent" for e in events(client, ada["id"]))


def test_message_loops_are_cut_after_max_depth(client, scripts):
    client.app.state.engine.settings.max_message_depth = 1
    ada, rex = make(client, name="Ada"), make(client, name="Rex")
    scripts["ada"] = [use(call("send_message", to="rex", message="ping")), say("Sent.")]
    scripts["rex"] = [use(call("send_message", to="ada", message="pong")), say("Tried.")]
    chat(client, ada["id"], "Start.")
    for _ in range(3):
        wake_everyone(client)
    results = [e["text"] for e in events(client, rex["id"]) if e["kind"] == "tool_result"]
    assert any("Not sent" in r for r in results)
    assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "sleeping"


def test_a_dottie_can_schedule_itself(client, scripts):
    ada = make(client)
    scripts["ada"] = [
        use(
            call("create_schedule", title="Weekly review", prompt="Review the wiki.", cron="0 9 * * 1", timezone="UTC")
        ),
        say("Scheduled."),
    ]
    chat(client, ada["id"], "Review your wiki every Monday at 9.")
    wake_everyone(client)
    schedules = client.get(f"/api/dotties/{ada['id']}/schedules").json()
    assert [(s["title"], s["cron"], s["created_by"]) for s in schedules] == [("Weekly review", "0 9 * * 1", "dottie")]


def test_without_a_model_the_user_is_told_why(client, settings):
    ada = make(client)
    client.app.state.engine.runner.settings = settings.model_copy(update={"llm_base_url": ""})
    client.app.state.engine.runner.model_factory = __import__("dottie.engine.agent", fromlist=["x"]).build_model
    conversation = chat(client, ada["id"], "Hello?")
    wake_everyone(client)
    reply = client.get(f"/api/conversations/{conversation}/messages").json()[-1]
    assert reply["sender_kind"] == "system" and "no model" in reply["body"]
    assert client.get(f"/api/dotties/{ada['id']}/runs").json()[0]["status"] == "failed"


def test_deleting_a_conversation_and_a_dottie_cleans_up(client, scripts):
    ada = make(client)
    scripts["ada"] = [say("Hi.")]
    conversation = chat(client, ada["id"], "Hello")
    wake_everyone(client)
    assert client.delete(f"/api/conversations/{conversation}").status_code == 204
    assert client.get(f"/api/dotties/{ada['id']}/conversations").json() == []
    assert client.delete(f"/api/dotties/{ada['id']}").status_code == 204
    assert client.get("/api/events").json() == []


def test_a_dottie_woken_by_another_can_tell_the_user(client, scripts):
    ada, rex = make(client, name="Ada"), make(client, name="Rex")
    scripts["rex"] = [use(call("send_message", to="ada", message="The title is Example Domain.")), say("Sent.")]
    scripts["ada"] = [use(call("tell_user", message="Rex says the title is Example Domain.")), say("Passed it on.")]
    chat(client, rex["id"], "Find the title of example.com and tell Ada.")
    for _ in range(3):
        wake_everyone(client)
    inbox = client.get("/api/inbox").json()
    assert [(i["dottie_name"], i["message"]["body"]) for i in inbox if i["dottie_name"] == "Ada"] == [
        ("Ada", "Rex says the title is Example Domain.")
    ]
    assert ada["id"] != rex["id"]
