"""End-to-end API tests against a fake GitHub. Run from backend/: python -m pytest"""
import base64
import hashlib
import hmac
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app import github_client
from app.config import settings
from app.main import app

REPO = "acme/legacy"
BASE_SHA, HEAD_SHA = "a" * 40, "b" * 40


def commit(sha: str, message: str) -> dict:
    return {
        "sha": sha, "html_url": f"https://github.com/{REPO}/commit/{sha}",
        "author": {"login": "ayaan", "avatar_url": "https://a"},
        "commit": {"message": message, "author": {"name": "Ayaan", "date": "2026-11-07T20:00:00Z"}},
    }


class FakeGitHub:
    def __init__(self):
        self.two_factor = True
        self.can_push = True
        self.head = BASE_SHA
        self.files = {}  # path -> (sha, content) on the intent branch
        self.branches = {"main": BASE_SHA}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        p, m = req.url.path, req.method
        if p == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "tok"})
        if p == "/user":
            return httpx.Response(200, json={
                "id": 7, "login": "ayaan", "name": "Ayaan", "avatar_url": "a", "html_url": "h",
                **({} if self.two_factor is None else {"two_factor_authentication": self.two_factor}),
            })
        if p == "/user/repos":
            return httpx.Response(200, json=[{
                "id": 1, "full_name": REPO, "private": True, "default_branch": "main",
                "language": "Python", "updated_at": "x", "permissions": {"push": True},
            }])
        if p == f"/repos/{REPO}" or p == "/repos/ACME/legacy":
            return httpx.Response(200, json={
                "full_name": REPO, "default_branch": "main",
                "permissions": {"pull": True, "push": self.can_push},
            })
        if p == "/repos/acme/secret":
            return httpx.Response(404, json={"message": "Not Found"})
        if p == f"/repos/{REPO}/commits/main":
            return httpx.Response(200, json={"sha": self.head})
        if p == f"/repos/{REPO}/commits/{HEAD_SHA}":
            if req.headers["accept"] == "application/vnd.github.diff":
                return httpx.Response(200, text="diff --git a/big.bin b/big.bin\n")
            return httpx.Response(200, json={
                **commit(HEAD_SHA, "Fix session expiry\n\nLonger body."),
                "parents": [{"sha": BASE_SHA}], "stats": {"total": 4, "additions": 3, "deletions": 1},
                "files": [
                    {"filename": "src/auth/session.py", "status": "modified", "additions": 3, "deletions": 1, "changes": 4, "patch": "@@ -1 +1 @@"},
                    {"filename": "big.bin", "status": "modified", "additions": 0, "deletions": 0, "changes": 900},
                ],
            })
        if p == f"/repos/{REPO}/commits/{'c' * 40}":
            return httpx.Response(422, json={"message": "No commit found for SHA"})
        if p == f"/repos/{REPO}/commits":
            path = req.url.params.get("path")
            history = [commit(HEAD_SHA, "Fix session expiry"), commit(BASE_SHA, "Initial import")]
            if path == "src/db/user.py":
                history = history[1:]
            return httpx.Response(200, json=history[: int(req.url.params.get("per_page", 30))])
        if p == f"/repos/{REPO}/branches/main":
            return httpx.Response(200, json={"name": "main", "commit": {"sha": self.head}})
        if p == f"/repos/{REPO}/branches":
            return httpx.Response(200, json=[{"name": "main", "commit": {"sha": self.head}}, {"name": "Login", "commit": {"sha": HEAD_SHA}}])
        if p == f"/repos/{REPO}/compare/main...Login":
            if req.headers["accept"] == "application/vnd.github.diff":
                return httpx.Response(200, text="diff --git a/x b/x\n")
            return httpx.Response(200, json={
                "status": "ahead", "ahead_by": 1, "behind_by": 0,
                "commits": [commit(HEAD_SHA, "Fix session expiry")],
                "files": [{"filename": "src/auth/session.py", "status": "modified", "additions": 3, "deletions": 1, "patch": "@@"}],
            })
        if p == f"/repos/{REPO}/compare/{BASE_SHA}...{HEAD_SHA}":
            return httpx.Response(200, json={"ahead_by": 1, "files": [
                {"filename": "src/auth/session.py", "status": "modified", "additions": 3, "deletions": 1,
                 "patch": "@@ -1,3 +1,5 @@\n def validate(t):\n-    return t\n+    if expired(t):\n+        raise SessionError\n+    return t\n # end"},
                {"filename": "src/new.py", "status": "renamed", "previous_filename": "src/old.py"},
            ]})
        if p == f"/repos/{REPO}/git/trees/main":
            return httpx.Response(200, json={"sha": "t", "tree": [
                {"path": "src", "type": "tree", "sha": "1"},
                {"path": "src/auth/session.py", "type": "blob", "sha": "2", "size": 10},
            ]})
        if p == f"/repos/{REPO}/contents/src/auth/session.py":
            return httpx.Response(200, json={
                "type": "file", "path": "src/auth/session.py", "sha": "2", "size": 12,
                "content": base64.b64encode(b"def check():\n").decode(),
            })
        ref = re.match(rf"/repos/{REPO}/git/ref/heads/(.+)", p)
        if ref:
            name = ref.group(1)
            if name not in self.branches:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"object": {"sha": self.branches[name]}})
        if p == f"/repos/{REPO}/git/refs" and m == "POST":
            body = json.loads(req.content)
            self.branches[body["ref"][len("refs/heads/"):]] = body["sha"]
            return httpx.Response(201, json={})
        content = re.match(rf"/repos/{REPO}/contents/(.+)", p)
        if content:
            path = content.group(1)
            if m == "GET":
                if path not in self.files:
                    return httpx.Response(404, json={"message": "Not Found"})
                return httpx.Response(200, json={"sha": self.files[path][0]})
            body = json.loads(req.content)
            if path in self.files and body.get("sha") != self.files[path][0]:
                return httpx.Response(409, json={"message": "sha mismatch"})
            sha = f"f{len(self.files)}{len(body['content'])}"
            self.files[path] = (sha, base64.b64decode(body["content"]).decode())
            return httpx.Response(200, json={"commit": {"sha": "c1"}, "content": {"html_url": "https://x"}})
        return httpx.Response(500, json={"message": f"unmocked {m} {p}"})


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "github_client_id", "cid")
    monkeypatch.setattr(settings, "require_2fa", True)
    monkeypatch.setattr(settings, "webhook_secret", "whsec")
    gh = FakeGitHub()
    monkeypatch.setattr(github_client, "transport", httpx.MockTransport(gh))
    return gh


def login(c: TestClient) -> httpx.Response:
    r = c.get("/auth/github/login")
    state = re.search(r"state=([^&]+)", r.headers["location"]).group(1)
    return c.get(f"/auth/github/callback?code=x&state={state}")


@pytest.fixture
def client(fake):
    with TestClient(app, follow_redirects=False) as c:
        r = login(c)
        assert r.headers["location"].endswith("/dashboard")
        yield c


# ------------------------------------------------------------------ auth


def test_rejects_account_without_2fa(fake):
    fake.two_factor = False
    with TestClient(app, follow_redirects=False) as c:
        assert login(c).headers["location"].endswith("/login?error=2fa_required")
        assert c.get("/auth/me").status_code == 401


def test_2fa_not_reported_gets_its_own_error(fake, caplog):
    fake.two_factor = None  # GitHub left the field out
    with TestClient(app, follow_redirects=False) as c:
        assert login(c).headers["location"].endswith("/login?error=2fa_unknown")
    assert "did not report 2FA status" in caplog.text


def test_error_responses_carry_codes(fake):
    with TestClient(app) as c:
        r = c.get("/api/repos")
        assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"
        assert c.get("/no/such/route").json()["code"] == "NOT_FOUND"


def test_2fa_check_can_be_disabled(fake, monkeypatch):
    fake.two_factor = False
    monkeypatch.setattr(settings, "require_2fa", False)
    with TestClient(app, follow_redirects=False) as c:
        assert login(c).headers["location"].endswith("/dashboard")


def test_rejects_bad_state(fake):
    with TestClient(app, follow_redirects=False) as c:
        c.get("/auth/github/login")
        r = c.get("/auth/github/callback?code=x&state=forged")
        assert r.headers["location"].endswith("error=invalid_state")


def test_requires_login(fake):
    with TestClient(app) as c:
        assert c.get("/api/repos").status_code == 401
        assert c.get(f"/api/repos/{REPO}/changes").status_code == 401
        assert c.get("/api/workspaces/1/tree").status_code == 401


def test_me_and_logout(client):
    assert client.get("/auth/me").json()["login"] == "ayaan"
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401


# ------------------------------------------------------------------ github views


def test_tree_and_file(client):
    tree = client.get(f"/api/github/repos/{REPO}/tree").json()
    assert [f["path"] for f in tree["files"]] == ["src/auth/session.py"]
    f = client.get(f"/api/github/repos/{REPO}/file", params={"path": "src/auth/session.py"}).json()
    assert f["content"] == "def check():\n"


def test_commit_history_and_file_history(client):
    history = client.get(f"/api/github/repos/{REPO}/commits").json()
    assert [c["message"] for c in history] == ["Fix session expiry", "Initial import"]
    assert history[0]["author"] == "ayaan" and history[0]["html_url"].endswith(HEAD_SHA)
    one_file = client.get(f"/api/github/repos/{REPO}/commits", params={"path": "src/db/user.py"}).json()
    assert [c["sha"] for c in one_file] == [BASE_SHA]
    assert len(client.get(f"/api/github/repos/{REPO}/commits", params={"limit": 1}).json()) == 1


def test_commit_detail_includes_diffs(client):
    c = client.get(f"/api/github/repos/{REPO}/commits/{HEAD_SHA}").json()
    assert c["message"] == "Fix session expiry" and "Longer body." in c["full_message"]
    assert c["parents"] == [BASE_SHA] and c["stats"]["total"] == 4
    session_py, big = c["files"]
    assert session_py["patch"] == "@@ -1 +1 @@" and session_py["patch_truncated"] is False
    assert session_py["changed_lines"] == {"added": [], "removed": []}  # hunk header only
    assert big["patch"] is None and big["patch_truncated"] is True


def test_raw_diff_for_truncated_files(client):
    r = client.get(f"/api/github/repos/{REPO}/diff", params={"sha": HEAD_SHA})
    assert r.status_code == 200 and r.text.startswith("diff --git a/big.bin")
    r = client.get(f"/api/github/repos/{REPO}/diff", params={"base": "main", "head": "Login"})
    assert r.text.startswith("diff --git a/x")
    assert client.get(f"/api/github/repos/{REPO}/diff").status_code == 422


def test_compare_any_two_refs(client):
    cmp = client.get(f"/api/github/repos/{REPO}/compare", params={"base": "main", "head": "Login"}).json()
    assert cmp["ahead_by"] == 1 and cmp["status"] == "ahead"
    assert [c["message"] for c in cmp["commits"]] == ["Fix session expiry"]
    assert [f["path"] for f in cmp["files"]] == ["src/auth/session.py"]
    branches = client.get(f"/api/github/repos/{REPO}/branches").json()
    assert [b["name"] for b in branches] == ["main", "Login"]


@pytest.mark.parametrize("ref", ["../../user", "main..Login", "/etc", "a b"])
def test_rejects_refs_that_could_escape_the_repo(client, ref):
    assert client.get(f"/api/github/repos/{REPO}/compare", params={"base": ref, "head": "main"}).status_code == 422
    assert client.get(f"/api/github/repos/{REPO}/commits", params={"ref": ref}).status_code == 422


@pytest.mark.parametrize("path", ["../secrets", "src/../../user", "/abs", "a//b"])
def test_rejects_paths_that_could_escape_the_repo(client, path):
    assert client.get(f"/api/github/repos/{REPO}/file", params={"path": path}).status_code == 422
    assert client.get(f"/api/github/repos/{REPO}/commits", params={"path": path}).status_code == 422


def test_unknown_commit_is_reported(client):
    r = client.get(f"/api/github/repos/{REPO}/commits/{'c' * 40}")
    assert r.status_code == 422 and "No commit found" in r.json()["detail"]


# ------------------------------------------------------------------ repos


def test_connect_requires_access(client):
    r = client.post("/api/repos/acme/secret/connect")
    assert r.status_code == 404


def test_connect_is_case_insensitive_and_idempotent(client):
    assert client.post(f"/api/repos/{REPO}/connect").json()["can_push"] is True
    client.post("/api/repos/ACME/legacy/connect")
    repos = client.get("/api/repos").json()
    assert [r["full_name"] for r in repos] == [REPO]
    assert client.get("/api/repos/ACME/LEGACY").status_code == 200


def test_unconnected_repo_is_404(client):
    assert client.get(f"/api/repos/{REPO}/changes").status_code == 404


def test_repo_graph_is_built_from_the_synced_snapshot_and_requires_a_session(tmp_path, monkeypatch):
    """The Codebase view's graph for a connected repo: files as intent nodes, imports as edges."""
    from app import db, sessions
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))  # a fresh intent folder, whatever workspace id the db hands out
    from app.actors import Actor
    from app.intent.store import IntentStore

    with TestClient(app) as c:
        uid = db.upsert_user(901, "graph-tester")
        with db.connect() as conn:
            conn.execute("DELETE FROM repos WHERE user_id = ? AND full_name = ?", (uid, "o/graphy"))
        sid = sessions.create_session("tok", {"login": "graph-tester"}, uid)
        with db.connect() as conn:
            conn.execute("INSERT INTO repos (user_id, full_name, default_branch, connected_at) VALUES (?,?,?,?)",
                         (uid, "o/graphy", "main", 0))
        rid = db.fetch_repo(uid, "o/graphy")["id"]
        assert c.get("/api/repos/o/graphy/graph").status_code == 401
        c.cookies.set("intentflow_session", sid)
        assert c.get("/api/repos/o/graphy/graph").json()["nodes"] == []  # not synced yet
        store = IntentStore(rid)
        store.put_imports({"head": "x", "external": [],
                           "files": [{"path": "src/a.py", "size": 4000}, {"path": "src/b.py", "size": 800}, {"path": "README.md", "size": 5}],
                           "edges": [{"source": "src/a.py", "target": "src/b.py"}]})
        store.put_annotation(Actor(kind="engine", name="t"), "src/a.py",
                             {"path": "src/a.py", "file_hash": "h", "chunks": [],
                              "summary": {"purpose": "Does A", "responsibilities": [], "dependencies": [], "sections": []}})
        g = c.get("/api/repos/o/graphy/graph").json()
        assert {n["node_id"] for n in g["nodes"]} == {"src/a.py", "src/b.py"}  # README is not source
        assert g["edges"] == [{"source": "src/a.py", "target": "src/b.py", "relation": "imports"}]
        a = next(n for n in g["nodes"] if n["node_id"] == "src/a.py")
        assert a["intent_summary"] == "Does A" and a["meta"]["raw_tokens"] == 1000
        with c.websocket_connect("/api/repos/o/graphy/graph") as ws:
            assert ws.receive_json()["type"] == "snapshot"
