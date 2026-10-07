from .test_dotties import make


def test_user_edits_a_page_and_it_is_marked_as_the_user_s(client):
    ada = make(client)
    url = f"/api/dotties/{ada['id']}/wiki/people/anna.md"
    assert client.get(url).status_code == 404
    saved = client.put(url, json={"content": "# Anna\nLikes tea."}).json()
    assert (saved["path"], saved["updated_by"]) == ("people/anna.md", "user")
    assert client.get(url).json()["content"] == "# Anna\nLikes tea."
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_paths_cannot_leave_the_wiki(client):
    ada = make(client)
    assert client.put(f"/api/dotties/{ada['id']}/wiki/..%2Fsecret.md", json={"content": "x"}).status_code in (404, 422)
    assert client.put(f"/api/dotties/{ada['id']}/wiki/a%2F..%2F..%2Fb.md", json={"content": "x"}).status_code == 422
