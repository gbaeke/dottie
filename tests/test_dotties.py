def make(client, **fields):
    res = client.post("/api/dotties", json={"name": "Ada", **fields})
    assert res.status_code == 201, res.text
    return res.json()


def test_create_gives_a_slug_a_wiki_and_a_sleeping_state(client):
    ada = make(client, role="Chief of staff", personality="Calm.")
    assert ada["slug"] == "ada"
    assert ada["state"] == "sleeping"
    assert set(ada["tools"]) == {"messaging", "schedule", "web", "shell"}
    pages = client.get(f"/api/dotties/{ada['id']}/wiki").json()
    assert [p["path"] for p in pages] == ["index.md", "log.md", "user.md"]


def test_slugs_stay_unique(client):
    assert make(client, name="Ada")["slug"] == "ada"
    assert make(client, name="Ada")["slug"] == "ada-2"


def test_update_and_delete(client):
    ada = make(client)
    skill_id = client.get("/api/skills").json()[0]["id"]
    res = client.patch(
        f"/api/dotties/{ada['id']}",
        json={
            "personality": "Sharp.",
            "tools": ["web"],
            "skill_ids": [skill_id],
            "mcp_servers": [{"name": "docs", "url": "https://example.com/mcp"}],
        },
    )
    body = res.json()
    assert (body["personality"], body["tools"], body["skill_ids"]) == ("Sharp.", ["web"], [skill_id])
    assert body["mcp_servers"][0]["name"] == "docs"
    assert client.delete(f"/api/dotties/{ada['id']}").status_code == 204
    assert client.get(f"/api/dotties/{ada['id']}").status_code == 404


def test_unknown_toolkit_and_skill_are_rejected(client):
    assert client.post("/api/dotties", json={"name": "X", "tools": ["fly"]}).status_code == 422
    assert client.post("/api/dotties", json={"name": "X", "skill_ids": [999]}).status_code == 422


def test_templates_and_toolkits_are_listed(client):
    assert {t["key"] for t in client.get("/api/templates").json()} >= {"chief-of-staff", "researcher"}
    assert {t["key"] for t in client.get("/api/toolkits").json()} == {"messaging", "schedule", "web", "shell"}


def test_builtin_skills_are_seeded_and_cannot_be_changed(client):
    skills = client.get("/api/skills").json()
    assert {s["name"] for s in skills} >= {"wiki-keeper", "delegation"}
    assert client.delete(f"/api/skills/{skills[0]['id']}").status_code == 409


def test_own_skill_roundtrip(client):
    created = client.post("/api/skills", json={"name": "my-skill", "description": "When X.", "body": "Do Y."})
    assert created.status_code == 201
    assert client.post("/api/skills", json={"name": "my-skill", "description": "d", "body": "b"}).status_code == 409
    assert client.post("/api/skills", json={"name": "Bad Name", "description": "d", "body": "b"}).status_code == 422
    skill_id = created.json()["id"]
    assert client.patch(f"/api/skills/{skill_id}", json={"body": "Do Z."}).json()["body"] == "Do Z."
    assert client.delete(f"/api/skills/{skill_id}").status_code == 204


def test_every_model_gets_its_own_http_client(settings):
    """Runs have their own event loop: a client shared between them fails with 'Event loop is closed'."""
    from dottie.engine.agent import build_model
    from dottie.models import Dottie

    ada = Dottie(name="Ada", slug="ada")
    one, two = build_model(settings, ada), build_model(settings, ada)
    assert one.http_async_client is not two.http_async_client  # pyright: ignore[reportAttributeAccessIssue]
