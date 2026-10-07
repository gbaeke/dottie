from datetime import UTC, datetime, timedelta

from dottie.engine import scheduler

from .test_dotties import make


def test_recurring_schedule_gets_a_next_run(client):
    ada = make(client)
    res = client.post(
        f"/api/dotties/{ada['id']}/schedules",
        json={"title": "Briefing", "prompt": "Brief me.", "cron": "0 8 * * 1-5", "timezone": "Europe/Brussels"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["next_run_at"] and body["enabled"] and body["dottie_name"] == "Ada"


def test_bad_timing_is_rejected(client):
    ada = make(client)
    url = f"/api/dotties/{ada['id']}/schedules"
    base = {"title": "t", "prompt": "p"}
    assert client.post(url, json={**base, "cron": "not a cron"}).status_code == 422
    assert client.post(url, json={**base, "cron": "* * * * *", "timezone": "Mars/Base"}).status_code == 422
    assert client.post(url, json=base).status_code == 422  # neither cron nor run_at
    both = {**base, "cron": "* * * * *", "run_at": "2030-01-01T00:00:00Z"}
    assert client.post(url, json=both).status_code == 422


def test_due_schedule_wakes_the_dottie_with_a_message_and_a_one_off_ends(client, scripts):
    ada = make(client)
    soon = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    schedule = client.post(
        f"/api/dotties/{ada['id']}/schedules", json={"title": "Once", "prompt": "Say hi.", "run_at": soon}
    ).json()

    with client.app.state.session_factory() as s:
        assert scheduler.fire_due(s, datetime.now(UTC)) == 0  # not yet
        assert scheduler.fire_due(s, datetime.now(UTC) + timedelta(seconds=5)) == 1
        s.commit()

    after = client.get(f"/api/dotties/{ada['id']}/schedules").json()[0]
    assert after["id"] == schedule["id"] and after["enabled"] is False and after["last_run_at"]
    messages = client.get(f"/api/conversations/{after['conversation_id']}/messages").json()
    assert messages[0]["sender_kind"] == "scheduler" and "Say hi." in messages[0]["body"]
    assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "queued"


def test_run_now_and_toggle(client):
    ada = make(client)
    sid = client.post(
        f"/api/dotties/{ada['id']}/schedules", json={"title": "T", "prompt": "P", "cron": "0 8 * * *"}
    ).json()["id"]
    ran = client.post(f"/api/schedules/{sid}/run").json()
    assert ran["conversation_id"]
    paused = client.patch(f"/api/schedules/{sid}", json={"enabled": False}).json()
    assert paused["next_run_at"] is None
    assert client.patch(f"/api/schedules/{sid}", json={"enabled": True}).json()["next_run_at"]
    assert client.delete(f"/api/schedules/{sid}").status_code == 204
