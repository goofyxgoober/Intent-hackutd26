"""Intent engine: the spec's non-negotiable rules, sync, export and live events."""
import io
import json
import tarfile
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import github_client
from app.config import settings
from app.main import app
from tests.test_api import BASE_SHA, HEAD_SHA, REPO, FakeGitHub, login

KEYS = {"builder": "b" * 32, "test_runner": "r" * 32, "engine": "e" * 32}
FILES_BASE = {
    "src/auth/session.py": "from src.db import user\n\ndef validate(t):\n    return user.lookup(t)\n",
    "src/db/user.py": "def lookup(t):\n    return t\n",
    "src/old.py": "import os\n",
    "web/tsconfig.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./src/*"]}}}',
    "web/src/app.ts": 'import { api } from "@/api";\nimport React from "react";\n',
    "web/src/api.ts": "export const api = 1;\n",
}
FILES_HEAD = {**{k: v for k, v in FILES_BASE.items() if k != "src/old.py"},
              "src/auth/session.py": FILES_BASE["src/auth/session.py"] + "# changed\n", "src/new.py": "import os\n"}


def tarball(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"acme-legacy-abc123/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class RepoGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.trees = {}
        self.commits = {BASE_SHA: {"tree": "root0"}}
        self.refs = {"main": BASE_SHA}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        p, m = req.url.path, req.method
        if p.startswith(f"/repos/{REPO}/tarball/"):
            sha = p.rsplit("/", 1)[1]
            return httpx.Response(200, content=tarball(FILES_HEAD if sha == HEAD_SHA else FILES_BASE))
        if p == f"/repos/{REPO}/git/trees" and m == "POST":
            body = json.loads(req.content)
            sha = f"tree{len(self.trees)}"
            self.trees[sha] = body
            return httpx.Response(201, json={"sha": sha})
        if p.startswith(f"/repos/{REPO}/git/commits/") and m == "GET":
            return httpx.Response(200, json={"sha": p.rsplit("/", 1)[1], "tree": {"sha": "root0"}})
        if p == f"/repos/{REPO}/git/commits" and m == "POST":
            return httpx.Response(201, json={"sha": "newcommit"})
        if p.startswith(f"/repos/{REPO}/git/refs/heads/") and m == "PATCH":
            self.branches[p.split("/heads/", 1)[1]] = json.loads(req.content)["sha"]
            return httpx.Response(200, json={})
        return super().__call__(req)


@pytest.fixture
def gh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "github_client_id", "cid")
    monkeypatch.setattr(settings, "require_2fa", True)
    monkeypatch.setattr(settings, "webhook_secret", "whsec")
    monkeypatch.setattr(settings, "agent_keys", ",".join(f"{r}:{k}" for r, k in KEYS.items()))
    monkeypatch.setattr(settings, "reference_scope", "peer_children")
    fake = RepoGitHub()
    monkeypatch.setattr(github_client, "transport", httpx.MockTransport(fake))
    return fake


@pytest.fixture
def c(gh):
    with TestClient(app, follow_redirects=False) as client:
        login(client)
        client.wid = client.post(f"/api/repos/{REPO}/connect").json()["id"]
        yield client


def url(c, path=""):
    return f"/api/workspaces/{c.wid}{path}"


def as_agent(role):
    return {"Authorization": f"Bearer {KEYS[role]}", "X-Agent-Name": f"{role}-bot"}


def tenet(c, name, parent=None, role="builder", **kw):
    r = c.post(url(c, "/tenets"), json={"name": name, "parent_id": parent, "functionality": f"{name} does X", **kw},
               headers=as_agent(role) if role != "user" else None)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def claim(c, tid, statement="returns 401 for expired tokens", deps=(), role="builder"):
    r = c.post(url(c, f"/tenets/{tid}/claims"), json={
        "statement": statement, "test_explanation": "checks expiry", "test_implementation": "call validate()",
        "dependencies": list(deps)}, headers=as_agent(role) if role != "user" else None)
    assert r.status_code == 201, r.text
    return r.json()


def run(c, cl, verdict="pass", **kw):
    return c.post(url(c, f"/claims/{cl['id']}/results"), headers=as_agent("test_runner"),
                  json={"claim_hash": cl["content_hash"], "verdict": verdict, **kw})


def fresh(c, cid):
    return c.get(url(c, f"/claims/{cid}")).json()


@pytest.fixture
def tree(c):
    """root -> (auth -> validate), (db -> lookup)"""
    root = tenet(c, "system")
    auth = tenet(c, "auth", root)
    db_ = tenet(c, "db", root)
    validate = tenet(c, "validate", auth)
    lookup = tenet(c, "lookup", db_)
    return {"root": root, "auth": auth, "db": db_, "validate": validate, "lookup": lookup}


# ---------------------------------------------------------------- identity and permissions


def test_agent_keys_and_unknown_keys(c):
    assert c.get(url(c), headers=as_agent("engine")).json()["you"] == {"kind": "engine", "name": "engine-bot"}
    assert c.get(url(c), headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get(url(c)).json()["you"]["kind"] == "user"


def test_users_only_see_their_own_workspaces(c, gh):
    original = RepoGitHub.__call__

    def other(self, req):
        if req.url.path == "/user":
            return httpx.Response(200, json={"id": 99, "login": "vishjit", "two_factor_authentication": True})
        return original(self, req)

    github_client.transport = httpx.MockTransport(lambda r: other(gh, r))
    with TestClient(app, follow_redirects=False) as other_user:
        login(other_user)
        assert other_user.get(url(c, "/tree")).status_code == 404


def test_permission_matrix(c, tree):
    t = tree["validate"]
    # test runner: read only on Tenets and Claims
    assert c.post(url(c, "/tenets"), json={"name": "x", "parent_id": t}, headers=as_agent("test_runner")).status_code == 403
    assert c.post(url(c, f"/tenets/{t}/claims"), json={"statement": "s"}, headers=as_agent("test_runner")).status_code == 403
    # links are engine-only
    links = [{"path": "src/auth/session.py", "start_line": 1, "end_line": 4}]
    assert c.put(url(c, f"/tenets/{t}/links"), json=links, headers=as_agent("builder")).status_code == 403
    assert c.put(url(c, f"/tenets/{t}/links"), json=links).status_code == 403
    assert c.put(url(c, f"/tenets/{t}/links"), json=links, headers=as_agent("engine")).status_code == 200
    # results: test runner only
    cl = claim(c, t)
    assert c.post(url(c, f"/claims/{cl['id']}/results"), json={"claim_hash": cl["content_hash"], "verdict": "pass"}).status_code == 403
    assert c.post(url(c, f"/claims/{cl['id']}/results"), headers=as_agent("builder"),
                  json={"claim_hash": cl["content_hash"], "verdict": "pass"}).status_code == 403
    # annotations and spec: engine only
    assert c.put(url(c, "/annotations"), params={"path": "src/a.py"}, json={"summary": "s"}, headers=as_agent("builder")).status_code == 403
    assert c.put(url(c, "/annotations"), params={"path": "../etc/passwd"}, json={}, headers=as_agent("engine")).status_code == 422
    assert c.put(url(c, "/spec"), json={"markdown": "#"}, headers=as_agent("builder")).status_code == 403
    assert c.put(url(c, "/spec"), json={"markdown": "# Spec"}, headers=as_agent("engine")).status_code == 200


# ---------------------------------------------------------------- structure (section 4.3)


def test_one_root_and_strict_ownership(c, tree):
    r = c.post(url(c, "/tenets"), json={"name": "second root"}, headers=as_agent("builder"))
    assert r.status_code == 409
    view = c.get(url(c, "/tree")).json()
    assert view["root_id"] == tree["root"]
    levels = {t["name"]: t["level"] for t in view["tenets"]}
    assert levels == {"system": 0, "auth": 1, "db": 1, "validate": 2, "lookup": 2}
    assert c.post(url(c, f"/tenets/{tree['auth']}/move"), json={"parent_id": tree["validate"]}).status_code == 409
    assert c.post(url(c, f"/tenets/{tree['root']}/move"), json={"parent_id": tree["auth"]}).status_code == 409


def test_references_cross_branches_without_cycles(c, tree):
    ref = lambda src, dst: c.post(url(c, f"/tenets/{src}/references"), json={"target": dst}, headers=as_agent("builder"))
    assert ref(tree["auth"], tree["lookup"]).status_code == 200  # a peer's child
    assert ref(tree["auth"], tree["validate"]).status_code == 409  # already owned
    assert ref(tree["validate"], tree["root"]).status_code == 409  # ancestor
    assert ref(tree["auth"], tree["db"]).status_code == 409  # a peer itself, not its child
    info = c.get(url(c, f"/tenets/{tree['lookup']}")).json()
    assert info["referenced_by"] == [tree["auth"]]


def test_reference_scope_any_still_rejects_cycles(c, tree, monkeypatch):
    monkeypatch.setattr(settings, "reference_scope", "any")
    ref = lambda src, dst: c.post(url(c, f"/tenets/{src}/references"), json={"target": dst}, headers=as_agent("builder"))
    assert ref(tree["validate"], tree["lookup"]).status_code == 200
    assert ref(tree["lookup"], tree["validate"]).status_code == 409


def test_links_only_on_leaves_and_footprint_rolls_up(c, tree):
    eng = as_agent("engine")
    assert c.put(url(c, f"/tenets/{tree['auth']}/links"), json=[{"path": "src/x.py"}], headers=eng).status_code == 409
    c.put(url(c, f"/tenets/{tree['validate']}/links"), json=[{"path": "src/auth/session.py"}], headers=eng)
    c.put(url(c, f"/tenets/{tree['lookup']}/links"), json=[{"path": "src/db/user.py"}], headers=eng)
    assert c.post(url(c, "/tenets"), json={"name": "x", "parent_id": tree["validate"]}, headers=as_agent("builder")).status_code == 409
    paths = sorted(l["path"] for l in c.get(url(c, f"/tenets/{tree['root']}")).json()["footprint"])
    assert paths == ["src/auth/session.py", "src/db/user.py"]


# ---------------------------------------------------------------- Claims and results (rules 1-8)


def test_results_bind_to_wording_and_go_stale(c, tree):
    cl = claim(c, tree["validate"])
    assert run(c, {**cl, "content_hash": "0" * 64}).status_code == 409
    assert run(c, cl).json()["verdict"] == "pass"
    edited = c.patch(url(c, f"/claims/{cl['id']}"), json={"statement": "returns 403"}, headers=as_agent("builder")).json()
    assert edited["content_hash"] != cl["content_hash"]
    assert fresh(c, cl["id"])["result"]["verdict"] == "stale"


def test_three_valued_verdicts_and_underspecified(c, tree):
    cl = claim(c, tree["validate"])
    assert run(c, cl, "inconclusive").json()["verdict"] == "inconclusive"
    assert run(c, cl, "pass", underspecified="no fixture named").status_code == 422
    assert run(c, cl, "maybe").status_code == 422


def test_only_user_promotes_and_needs_a_pass(c, tree):
    cl = claim(c, tree["validate"])
    promote = lambda **kw: c.post(url(c, f"/claims/{cl['id']}/promote"), json=kw)
    assert c.post(url(c, f"/claims/{cl['id']}/promote"), json={}, headers=as_agent("builder")).status_code == 403
    untested = promote()
    assert untested.status_code == 409 and untested.json()["code"] == "NOT_VERIFIED"
    run(c, cl, "fail", code_ref="v1")
    assert promote().status_code == 409
    run(c, cl, "pass", code_ref="v2")  # code changed between runs: not flaky
    axiom = promote().json()
    assert axiom["status"] == "axiom" and axiom["verification"] == "verified"
    log = c.get(url(c, "/changelog")).json()
    assert log[-1]["type"] == "promote" and log[-1]["by"] == "ayaan"


def test_accept_without_verification_is_badged(c, tree):
    cl = claim(c, tree["validate"])
    r = c.post(url(c, f"/claims/{cl['id']}/promote"), json={"accept_without_verification": True}).json()
    assert r["status"] == "axiom" and r["verification"] == "accepted_without_verification"
    run(c, cl, "pass")
    assert fresh(c, cl["id"])["verification"] == "verified"


def test_flaky_results_block_promotion(c, tree):
    cl = claim(c, tree["validate"])
    run(c, cl, "pass", code_ref="v1")
    run(c, cl, "fail", code_ref="v1")
    run(c, cl, "pass", code_ref="v1")
    assert fresh(c, cl["id"])["result"]["flaky"] is True
    assert c.post(url(c, f"/claims/{cl['id']}/promote"), json={}).status_code == 409


def test_promotion_is_bottom_up(c, tree):
    leaf = claim(c, tree["validate"])
    feature = claim(c, tree["auth"], "auth hands the identity to db lookup", deps=[leaf["id"]])
    run(c, feature, "pass")
    r = c.post(url(c, f"/claims/{feature['id']}/promote"), json={})
    assert r.status_code == 409 and r.json()["detail"]["unmet"] == [leaf["id"]]
    assert r.json()["code"] == "DEPENDENCY_NOT_READY" and r.json()["detail"]["blockers"] == [leaf["id"]]
    run(c, leaf, "pass")  # passing is enough; locking also works
    assert c.post(url(c, f"/claims/{feature['id']}/promote"), json={}).json()["status"] == "axiom"


def test_dependency_cycles_rejected(c, tree):
    a = claim(c, tree["validate"], "a")
    b = claim(c, tree["validate"], "b", deps=[a["id"]])
    r = c.patch(url(c, f"/claims/{a['id']}"), json={"dependencies": [b["id"]]}, headers=as_agent("builder"))
    assert r.status_code == 409


def _axiom(c, tid, statement="returns 401 for expired tokens", deps=()):
    cl = claim(c, tid, statement, deps)
    run(c, cl, "pass")
    return c.post(url(c, f"/claims/{cl['id']}/promote"), json={}).json()


def test_agents_never_edit_axioms(c, tree):
    ax = _axiom(c, tree["validate"])
    for role in ("builder", "engine"):
        r = c.patch(url(c, f"/claims/{ax['id']}"), json={"statement": "x"}, headers=as_agent(role))
        assert r.status_code == 403 and r.json()["code"] == "AXIOM_LOCKED"
        r = c.put(url(c, f"/claims/{ax['id']}/axiom"), json={"statement": "x", "acknowledge_warning": True, "reason": "r"},
                  headers=as_agent(role))
        assert r.status_code == 403
    r = c.patch(url(c, f"/claims/{ax['id']}"), json={"statement": "x"})  # users use the warned flow
    assert r.status_code == 409 and r.json()["code"] == "AXIOM_LOCKED"


def test_hand_edit_of_axiom_needs_warning_and_flags_dependents(c, tree):
    ax = _axiom(c, tree["validate"])
    dep = claim(c, tree["auth"], "integration", deps=[ax["id"]])
    run(c, dep, "pass")
    r = c.put(url(c, f"/claims/{ax['id']}/axiom"), json={"statement": "returns 401 or 419"})
    assert r.status_code == 428 and r.json()["detail"]["impact"]["dependent_claims"][0]["id"] == dep["id"]
    r = c.put(url(c, f"/claims/{ax['id']}/axiom"),
              json={"statement": "returns 401 or 419", "acknowledge_warning": True, "reason": "legacy quirk"})
    edited = r.json()
    assert edited["status"] == "axiom" and edited["verification"] == "unverified_edit"
    after = fresh(c, dep["id"])
    assert after["flags"][0]["kind"] == "changed_base" and after["result"]["verdict"] == "stale"
    assert c.get(url(c, "/history"), params={"kind": "axiom_versions"}).json()[-1]["statement"] == ax["statement"]
    run(c, edited, "pass")
    assert fresh(c, ax["id"])["verification"] == "verified"


def test_failing_axiom_test_flags_but_never_changes(c, tree):
    ax = _axiom(c, tree["validate"])
    run(c, ax, "fail", notes="got 200")
    after = fresh(c, ax["id"])
    assert after["status"] == "axiom" and after["flags"][0]["kind"] == "test_failure"
    inbox = c.get(url(c, "/inbox")).json()
    assert [x["id"] for x in inbox["flagged_axioms"]] == [ax["id"]]
    assert c.delete(url(c, f"/claims/{ax['id']}/flags/test_failure"), headers=as_agent("builder")).status_code == 403
    assert c.delete(url(c, f"/claims/{ax['id']}/flags/test_failure")).json()["flags"] == []


def test_demotion_shows_impact_and_ripples(c, tree):
    c.put(url(c, f"/tenets/{tree['validate']}/links"), json=[{"path": "src/auth/session.py"}], headers=as_agent("engine"))
    leaf = _axiom(c, tree["validate"])
    feature = _axiom(c, tree["auth"], "auth composes validate", deps=[leaf["id"]])
    system = claim(c, tree["root"], "end to end", deps=[feature["id"]])
    run(c, system, "pass")

    impact = c.get(url(c, f"/claims/{leaf['id']}/impact")).json()
    assert [d["id"] for d in impact["dependent_claims"]] == [feature["id"], system["id"]]
    assert impact["affected_tenets"] == sorted([tree["auth"], tree["root"]])
    assert impact["linked_code"] == [{"path": "src/auth/session.py"}]
    assert set(impact["results_going_stale"]) == {leaf["id"], feature["id"], system["id"]}

    assert c.post(url(c, f"/claims/{leaf['id']}/demote"), json={"reason": "x"}, headers=as_agent("builder")).status_code == 403
    assert c.post(url(c, f"/claims/{leaf['id']}/demote"), json={"reason": ""}).status_code == 422
    r = c.post(url(c, f"/claims/{leaf['id']}/demote"), json={"reason": "legacy bug"}).json()
    assert r["status"] == "hypothesis" and r["impact"]["claim_id"] == leaf["id"]
    f = fresh(c, feature["id"])
    assert f["status"] == "axiom"  # no automatic demotion
    assert f["flags"][0]["kind"] == "unlocked_base" and f["result"]["verdict"] == "stale"
    # now an agent may edit it
    assert c.patch(url(c, f"/claims/{leaf['id']}"), json={"statement": "new"}, headers=as_agent("builder")).status_code == 200


def test_scrap_and_remake_with_failure_memory(c, tree):
    ax = _axiom(c, tree["validate"])
    assert c.post(url(c, f"/claims/{ax['id']}/scrap"), json={"reason": "r"}).status_code == 409
    h = claim(c, tree["validate"], "token is checked against the cache")
    assert c.post(url(c, f"/claims/{h['id']}/scrap"), json={"reason": "r"}, headers=as_agent("engine")).status_code == 403
    c.post(url(c, f"/claims/{h['id']}/scrap"), json={"reason": "cache is unrelated"}, headers=as_agent("builder"))
    rejected = c.get(url(c, f"/tenets/{tree['validate']}/rejected")).json()
    assert rejected[0]["interpretation"] == "token is checked against the cache"
    same = {"statement": "Token is checked against the cache ", "dependencies": []}
    assert c.post(url(c, f"/claims/{h['id']}/remake"), json=same, headers=as_agent("builder")).status_code == 409
    new = c.post(url(c, f"/claims/{h['id']}/remake"), json={"statement": "token signature is verified"},
                 headers=as_agent("builder")).json()
    assert new["remade_from"] == h["id"] and new["provenance"]["via"] == "remake"
    assert h["id"] not in c.get(url(c, "/tree")).json()["claims"]


def test_tenets_holding_axioms_cannot_be_deleted(c, tree):
    _axiom(c, tree["validate"])
    r = c.delete(url(c, f"/tenets/{tree['validate']}"), headers=as_agent("builder"))
    assert r.status_code == 409 and "Demote" in r.json()["detail"]["message"]
    assert c.delete(url(c, f"/tenets/{tree['auth']}")).status_code == 409  # has children
    assert c.delete(url(c, f"/tenets/{tree['lookup']}"), headers=as_agent("builder")).status_code == 204


def test_tree_rollups(c, tree):
    a = _axiom(c, tree["validate"])
    h = claim(c, tree["validate"], "second")
    run(c, h, "fail")
    v = {t["id"]: t for t in c.get(url(c, "/tree")).json()["tenets"]}[tree["validate"]]
    assert (v["axioms"], v["hypotheses"], v["rollup"], v["is_leaf"]) == (1, 1, "fail", True)


# ---------------------------------------------------------------- Jev (sections 10.6, 12)


def test_jev_output_is_validated_against_the_tree(c, tree):
    ax = _axiom(c, tree["validate"])
    h = claim(c, tree["validate"], "hyp")
    post = lambda body: c.post(url(c, "/jev/verdicts"), json=body, headers=as_agent("engine"))
    base = {"confidence": "high", "reason": "touches validate"}
    assert post({**base, "verdict": "update_existing", "affected_claims": ["c_doesnotexist"]}).status_code == 422
    assert post({**base, "verdict": "update_existing", "affected_claims": [ax["id"]]}).status_code == 422
    assert post({**base, "verdict": "axiom_conflict", "affected_claims": [h["id"]]}).status_code == 422
    assert post({**base, "verdict": "sideways"}).status_code == 422
    assert c.post(url(c, "/jev/verdicts"), json={**base, "verdict": "no_disruption"}, headers=as_agent("builder")).status_code == 403
    assert post({**base, "verdict": "update_existing", "affected_claims": [h["id"]]}).status_code == 200
    assert post({**base, "verdict": "axiom_conflict", "affected_claims": [ax["id"]]}).status_code == 200
    assert fresh(c, ax["id"])["flags"][0]["kind"] == "jev_conflict"
    assert fresh(c, ax["id"])["status"] == "axiom"
    post({"verdict": "no_disruption", "confidence": "low", "reason": "unsure"})
    assert len(c.get(url(c, "/inbox")).json()["low_confidence_verdicts"]) == 1


# ---------------------------------------------------------------- sync and codebase (sections 9, 11.1, 12)


def test_initial_sync_ingests_codebase_with_import_edges(c):
    batch = c.post(f"/api/repos/{REPO}/sync").json()
    assert batch["initial"] is True and batch["head"] == BASE_SHA
    view = c.get(url(c, "/codebase")).json()
    edges = {(e["source"], e["target"]) for e in view["edges"]}
    assert ("src/auth/session.py", "src/db/user.py") in edges
    assert ("web/src/app.ts", "web/src/api.ts") in edges
    assert {"source": "web/src/app.ts", "package": "react"} in view["external"]
    root = next(f for f in view["folders"] if f["path"] == "")
    assert root["children"] == ["src", "web"]


def test_sync_batch_finds_affected_tenets_and_carries_renames(c, gh, tree):
    eng = as_agent("engine")
    c.post(f"/api/repos/{REPO}/sync")  # baseline at BASE_SHA
    c.put(url(c, f"/tenets/{tree['validate']}/links"), json=[{"path": "src/auth/session.py"}], headers=eng)
    c.put(url(c, f"/tenets/{tree['lookup']}/links"), json=[{"path": "src/old.py"}], headers=eng)
    c.post(url(c, f"/tenets/{tree['db']}/references"), json={"target": tree["validate"]}, headers=as_agent("builder"))
    c.put(url(c, "/annotations"), params={"path": "src/old.py"}, json={"summary": "old module"}, headers=eng)
    leaf = claim(c, tree["validate"])
    feature = claim(c, tree["db"], "db integrates validate")

    gh.head = HEAD_SHA
    batch = c.post(f"/api/repos/{REPO}/sync").json()
    assert batch["status"] == "awaiting_review" and batch["base"] == BASE_SHA and batch["head"] == HEAD_SHA
    assert batch["changed_leaves"] == sorted([tree["validate"], tree["lookup"]])
    assert set(batch["affected_tenets"]) == {tree["validate"], tree["lookup"], tree["auth"], tree["db"], tree["root"]}
    assert set(batch["rerun_claims"]) == {leaf["id"], feature["id"]}
    assert batch["renames"] == {"src/old.py": "src/new.py"}
    # rename carried links and annotations
    assert c.get(url(c, f"/tenets/{tree['lookup']}")).json()["code_links"] == [{"path": "src/new.py"}]
    assert c.get(url(c, "/annotations"), params={"path": "src/new.py"}).json()["summary"] == "old module"
    assert c.get(url(c, "/codebase")).json()["head"] == HEAD_SHA
    # Jev reviews the batch
    c.post(url(c, "/jev/verdicts"), headers=eng, json={"verdict": "no_disruption", "confidence": "high",
                                                       "reason": "comment only", "batch_id": batch["id"]})
    assert c.get(url(c, f"/sync/batches/{batch['id']}")).json()["status"] == "reviewed"


def test_webhook_pushes_are_debounced_into_one_batch(c, gh, monkeypatch):
    import hashlib
    import hmac
    monkeypatch.setattr(settings, "sync_debounce_seconds", 0.2)
    c.post(f"/api/repos/{REPO}/sync")
    gh.head = HEAD_SHA

    def push(after):
        body = json.dumps({"ref": "refs/heads/main", "before": BASE_SHA, "after": after,
                           "repository": {"full_name": REPO, "default_branch": "main"},
                           "commits": [{"message": f"commit {after[:4]}"}]}).encode()
        sig = "sha256=" + hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
        return c.post("/webhooks/github", content=body, headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": sig})

    assert push("c" * 40).status_code == 204
    assert push(HEAD_SHA).status_code == 204
    time.sleep(0.6)
    batches = c.get(url(c, "/sync/batches")).json()
    webhook = [b for b in batches if b["source"] == "webhook"]
    assert len(webhook) == 1 and webhook[0]["head"] == HEAD_SHA
    assert webhook[0]["hints"] == ["commit cccc", "commit bbbb"]


def test_webhook_rejects_bad_signatures(c):
    r = c.post("/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=0"})
    assert r.status_code == 401


# ---------------------------------------------------------------- export and live events


def test_export_commits_folder_to_intent_branch(c, gh, tree):
    _axiom(c, tree["validate"])
    r = c.post(url(c, "/export")).json()
    assert r["branch"] == "intentflow/intents" and r["changed"] is True
    folder = gh.trees["tree0"]["tree"]
    paths = {e["path"] for e in folder}
    assert ".gitignore" in paths and not any(p.startswith("results/") for p in paths)
    assert any(p.endswith(f"validate--{tree['validate']}/tenet.json") and p.startswith("tenets/system--") for p in paths)
    assert gh.trees["tree1"]["tree"] == [{"path": ".intentflow", "mode": "040000", "type": "tree", "sha": "tree0"}]
    assert gh.branches["intentflow/intents"] == "newcommit"
    assert c.post(url(c, "/export"), headers=as_agent("engine")).status_code == 403


def test_flags_are_announced_live(c, tree):
    ax = _axiom(c, tree["validate"])
    with c.websocket_connect(f"/ws/workspaces/{c.wid}") as ws:
        ws.receive_json()  # hello
        run(c, ax, "fail", notes="got 200 for an expired token")
        seen = [ws.receive_json() for _ in range(2)]
    flag = next(e for e in seen if e["type"] == "flag.raised")
    assert flag["claim_id"] == ax["id"] and flag["kind"] == "test_failure" and flag["status"] == "axiom"
    assert flag["reason"] == "got 200 for an expired token"


def test_chat_provenance_is_accepted(c, tree):
    r = c.post(url(c, f"/tenets/{tree['validate']}/claims"),
               json={"statement": "user's own words", "provenance": {"via": "chat"}})
    assert r.status_code == 201 and r.json()["provenance"]["via"] == "chat"


def test_websocket_streams_workspace_events(c, tree):
    with c.websocket_connect(f"/ws/workspaces/{c.wid}") as ws:
        assert ws.receive_json()["type"] == "hello"
        claim(c, tree["validate"])
        assert ws.receive_json()["type"] == "claim.created"
    with c.websocket_connect(f"/ws/workspaces/{c.wid}?key={KEYS['test_runner']}") as ws:
        assert ws.receive_json()["you"] == "test_runner"


# ---------------------------------------------------------------- polling


def test_poller_syncs_new_commits_with_changed_lines(c, gh, monkeypatch):
    from app import sync

    c.post(f"/api/repos/{REPO}/sync")  # baseline at BASE_SHA
    monkeypatch.setattr(settings, "poll_interval_seconds", 0.1)
    sync.stop_all()
    c.get(url(c))  # any use of the workspace (re)starts its poller
    time.sleep(0.3)
    status = c.get(url(c, "/sync/status")).json()
    assert status["polling"] is True and status["last_seen_head"] == BASE_SHA
    assert c.get(url(c, "/sync/latest")).json() is None  # nothing changed yet

    gh.head = HEAD_SHA  # someone pushes
    deadline = time.time() + 3
    while time.time() < deadline and c.get(url(c, "/sync/latest")).json() is None:
        time.sleep(0.1)
    latest = c.get(url(c, "/sync/latest")).json()
    assert latest["source"] == "poll" and latest["base"] == BASE_SHA and latest["head"] == HEAD_SHA
    session_py = next(f for f in latest["files"] if f["path"] == "src/auth/session.py")
    assert session_py["changed_lines"] == {"added": [[2, 4]], "removed": [[2, 2]]}
    assert c.get(url(c)).json()["last_synced_sha"] == HEAD_SHA
    # the next poll sees no new commit and creates nothing
    count = len(c.get(url(c, "/sync/batches")).json())
    time.sleep(0.3)
    assert len(c.get(url(c, "/sync/batches")).json()) == count


def test_check_now_and_idle_stop(c, gh, monkeypatch):
    from app import sync

    c.post(f"/api/repos/{REPO}/sync")
    gh.head = HEAD_SHA
    r = c.post(url(c, "/sync/check")).json()
    assert r["changed"] is True and r["batch"]["head"] == HEAD_SHA
    assert c.post(url(c, "/sync/check")).json()["changed"] is False

    monkeypatch.setattr(settings, "poll_interval_seconds", 0.05)
    monkeypatch.setattr(settings, "poll_idle_stop_seconds", 0)
    sync.stop_all()
    c.get(url(c))
    time.sleep(0.3)
    # idle, so it stopped (reading /sync/status would count as use and restart it)
    task = sync._pollers.get(c.wid)
    assert task is None or task.done()


def test_polling_can_be_turned_off(c, monkeypatch):
    from app import sync

    monkeypatch.setattr(settings, "poll_interval_seconds", 0)
    sync.stop_all()
    c.get(url(c))
    assert c.get(url(c, "/sync/status")).json()["polling"] is False
