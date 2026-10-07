def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_unknown_api_path_is_a_json_404(client):
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_responses_carry_a_request_id_and_security_headers(client):
    res = client.get("/api/health", headers={"x-request-id": "abc"})
    assert res.headers["x-request-id"] == "abc"
    assert res.headers["x-content-type-options"] == "nosniff"
