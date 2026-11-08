"""Intent Builder grilling: the hierarchy is built level by level from the user's answers."""
import pytest

from app import grill, pipeline
from app.actors import Actor
from app.config import settings
from app.intent.store import IntentStore

FILES = [
    "src/auth/session.py",
    "src/auth/token.py",
    "src/db/user.py",
    "src/db/pool.py",
    "web/app.ts",
    "web/src/api.ts",
    "web/tsconfig.json",
]
WS = 42


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setenv("INTENT_MAX_DEPTH", "3")
    monkeypatch.setattr(grill, "_llm_json", lambda *a, **k: None)  # offline unless a test scripts it
    s = IntentStore(WS)
    s.put_imports({"head": "x", "files": [{"path": p, "size": 1, "language": "python"} for p in FILES],
                   "edges": [], "external": []})
    engine = Actor(kind="engine", name="t")
    s.put_annotation(engine, "src/auth/session.py", {"summary": {"purpose": "Validates session tokens.",
                                                                 "invariants": ["Expired tokens are rejected"]}})
    pipeline.generate_requirements_and_tenets(s, {"files": [{"path": p} for p in FILES]}, "acme/legacy")
    # files under a generic folder at the top level form a "Core" feature
    s.put_imports({"head": "x", "files": [{"path": p, "size": 1, "language": "x"} for p in FILES], "edges": [], "external": []})
    return s


def tree(store):
    t = store.tenets()
    return t, {tid: IntentStore.level(t, tid) for tid in t}


def answer_all(max_steps=60, reply="A"):
    """Answer every question with `reply`; return the (tenet_id, level) of each tenet grilled, in order."""
    visited = []
    status = grill.get_grill_status(WS)
    for _ in range(max_steps):
        if not status.get("active"):
            break
        if not visited or visited[-1][0] != status["tenet_id"]:
            visited.append((status["tenet_id"], status["level"]))
        grill.submit_grill_answer(WS, reply)
        status = grill.get_grill_status(WS)
    return visited


def started_with_one_hypothesis(store):
    """Every Tenet has a Hypothesis from creation; none is an Axiom and none has a fake test."""
    claims = store.claims()
    for t in store.tenets().values():
        own = [claims[c] for c in t["claims"] if c in claims]
        assert own, f"{t['name']} has no Hypothesis"
    assert all(c["status"] == "hypothesis" and c["test_implementation"] == "" for c in claims.values())
    return claims


def test_pipeline_makes_root_and_features_each_with_a_hypothesis(store):
    tenets, levels = tree(store)
    root = next(t for t in tenets.values() if not t["parent_id"])
    assert root["name"] == "Legacy"
    features = sorted(tenets[c]["name"] for c in root["children"])
    assert features == ["Auth", "Db", "Web"]
    claims = started_with_one_hypothesis(store)
    assert all(len(t["claims"]) == 1 for t in tenets.values())
    auth = next(t for t in tenets.values() if t["name"] == "Auth")
    # taken from the code: the rule session.py's annotation says it enforces
    assert claims[auth["claims"][0]]["statement"] == "Expired tokens are rejected"
    root_claim = claims[root["claims"][0]]["statement"]
    assert root_claim.startswith("Legacy combines") and "Auth" in root_claim
    auth = next(t for t in tenets.values() if t["name"] == "Auth")
    assert "Validates session tokens." in auth["functionality"]  # from the file's own annotation


def test_grilling_builds_the_hierarchy_level_by_level(store):
    start = grill.start_grill_session(WS)
    assert start["level"] == 0 and start["level_name"] == "system"
    assert 1 <= len(start["questions"]) <= 3

    visited = answer_all()
    levels_in_order = [lvl for _, lvl in visited]
    assert levels_in_order == sorted(levels_in_order), "a deeper level started before the one above finished"
    assert levels_in_order[0] == 0 and set(levels_in_order) >= {0, 1, 2}

    tenets, levels = tree(store)
    assert max(levels.values()) >= 2, "grilling should build tenets below the features"
    started_with_one_hypothesis(store)  # including every tenet grilling created
    auth = next(t for t in tenets.values() if t["name"] == "Auth")
    assert sorted(tenets[c]["name"] for c in auth["children"]) == ["Session", "Token"]
    # code links live on leaves only, and every file is still covered exactly once
    for t in tenets.values():
        if t["children"]:
            assert t["code_links"] == []
    leaf_files = sorted(l["path"] for t in tenets.values() if not t["children"] for l in t["code_links"])
    assert leaf_files == sorted(FILES)
    assert grill.get_grill_status(WS)["done"] is True


def test_answers_become_hypotheses_verbatim_without_fake_tests(store):
    grill.start_grill_session(WS)
    status = grill.get_grill_status(WS)
    rule = "Expired session tokens must be rejected with 401 before any DB lookup"
    for q in status["questions"]:
        text = rule if q["text"].startswith("What must ") else "A"
        grill.submit_grill_answer(WS, text, question_id=q["id"])
    from_answers = [c for c in store.claims().values() if c["provenance"].get("via") == "grilling"]
    assert [c["statement"] for c in from_answers] == [rule]
    assert from_answers[0]["status"] == "hypothesis"
    assert from_answers[0]["test_implementation"] == ""  # the Test Author writes real tests later


def test_one_word_replies_do_not_become_hypotheses(store):
    grill.start_grill_session(WS)
    before = set(store.claims())
    grill.submit_grill_answer(WS, "A")    # confirms the draft
    grill.submit_grill_answer(WS, "ok")   # not a rule
    assert set(store.claims()) == before


def test_typed_correction_replaces_the_draft(store):
    grill.start_grill_session(WS)
    first = grill.get_grill_status(WS)["current_question"]
    correction = "A billing system that charges customers monthly"
    grill.submit_grill_answer(WS, correction, question_id=first["id"])
    while grill.get_grill_status(WS)["tenet_name"] == "Legacy" and grill.get_grill_status(WS)["active"]:
        grill.submit_grill_answer(WS, "", dont_know=True)
    root = next(t for t in store.tenets().values() if not t["parent_id"])
    assert root["functionality"] == correction


def test_dont_know_is_recorded_and_never_blocks(store):
    grill.start_grill_session(WS)
    for _ in range(3):
        if not grill.get_grill_status(WS)["active"]:
            break
        grill.submit_grill_answer(WS, "", dont_know=True)
    state = grill.load_grill_state(WS)
    assert state["unknowns"]
    assert not [c for c in store.claims().values() if c["provenance"].get("via") == "grilling"]
    assert grill.get_grill_status(WS)["level"] == 1  # moved on to the features


def test_user_can_refuse_a_split(store):
    grill.start_grill_session(WS)
    while grill.get_grill_status(WS)["level"] == 0:
        grill.submit_grill_answer(WS, "A")
    status = grill.get_grill_status(WS)
    auth_id = status["tenet_id"]
    for q in status["questions"]:
        grill.submit_grill_answer(WS, "B" if q["text"].startswith("I'd split") else "A", question_id=q["id"])
    auth = store.tenet(auth_id)
    assert auth["children"] == [] and len(auth["code_links"]) == 2


def test_max_depth_stops_splitting(store, monkeypatch):
    monkeypatch.setenv("INTENT_MAX_DEPTH", "1")
    grill.start_grill_session(WS)
    answer_all()
    tenets, levels = tree(store)
    assert max(levels.values()) == 1


def test_llm_drives_questions_and_split(store, monkeypatch):
    calls = []

    def fake_llm(system, prompt, max_tokens=2500):
        calls.append(prompt)
        if "at most 3 short questions" in prompt:
            return {"draft": "LLM draft", "questions": [
                {"text": "I think this handles sign-in. Right?", "why": "w", "options": ["Yes", "No"]}]}
        if '"children"' in prompt and '"Auth"' in prompt:
            return {"functionality": "Signs users in.",
                    "hypotheses": [{"statement": "Expired tokens are rejected", "test_explanation": "t"}],
                    "children": [
                        {"name": "Session checks", "functionality": "f", "files": ["src/auth/session.py", "not/in/scope.py"]},
                    ]}
        return {"functionality": "", "hypotheses": [], "children": []}

    monkeypatch.setattr(grill, "_llm_json", fake_llm)
    grill.start_grill_session(WS)
    assert grill.get_grill_status(WS)["current_question"]["text"] == "I think this handles sign-in. Right?"
    answer_all()

    tenets, levels = tree(store)
    auth = next(t for t in tenets.values() if t["name"] == "Auth")
    assert auth["functionality"] == "Signs users in."
    kids = {tenets[c]["name"]: tenets[c] for c in auth["children"]}
    # invented paths are dropped; files the LLM left out go to an "Other" child so nothing is lost
    assert [l["path"] for l in kids["Session checks"]["code_links"]] == ["src/auth/session.py"]
    assert [l["path"] for l in kids["Other Auth code"]["code_links"]] == ["src/auth/token.py"]
    # the LLM's Hypothesis is added next to the starting one (same text, so not duplicated)
    assert [store.claim(c)["statement"] for c in auth["claims"]] == ["Expired tokens are rejected"]
    assert any("Signs users in" in p or "sign-in" in p for p in calls[1:]), "answers feed the next prompts"


def test_old_session_files_are_ignored(store):
    grill.save_grill_state(WS, {"id": "old", "tenet_id": "t_x", "questions": []})
    assert grill.get_grill_status(WS)["active"] is False


def test_rerunning_the_pipeline_keeps_grilling_progress(store):
    grill.start_grill_session(WS)
    grill.submit_grill_answer(WS, "A")
    before = grill.get_grill_status(WS)
    root = next(t["id"] for t in store.tenets().values() if not t["parent_id"])
    resumed = pipeline.start_tenet_grilling_session(WS, store, root, "acme/legacy")
    after = grill.get_grill_status(WS)
    assert resumed["current_question"]["id"] == before["current_question"]["id"]
    assert after["answered_count"] == 1
    # an explicit restart still starts over
    restarted = grill.start_grill_session(WS)
    assert grill.get_grill_status(WS)["answered_count"] == 0 and restarted["level"] == 0


def test_config_files_and_generic_folders_do_not_become_tenets(store):
    grill.start_grill_session(WS)
    answer_all()
    tenets, _ = tree(store)
    names = {t["name"] for t in tenets.values()}
    assert "Tsconfig" not in names and "Src" not in names
    web = next(t for t in tenets.values() if t["name"] == "Web")
    kids = {tenets[c]["name"]: tenets[c] for c in web["children"]}
    assert set(kids) == {"App", "Web core"}
    # the config file stays covered, attached to the code next to it
    covered = {l["path"] for k in kids.values() for l in k["code_links"]}
    assert "web/tsconfig.json" in covered


def test_confirmed_draft_loses_the_draft_label(store):
    grill.start_grill_session(WS)
    grill.submit_grill_answer(WS, "A")
    grill.submit_grill_answer(WS, "ok")
    root = next(t for t in store.tenets().values() if not t["parent_id"])
    assert not root["functionality"].startswith("Draft:")
    assert "Grilling confirms" not in root["functionality"]


def test_imports_across_branches_become_composition_references(store):
    store.put_imports({"head": "x", "files": [{"path": p, "size": 1, "language": "x"} for p in FILES],
                       "edges": [{"source": "src/auth/session.py", "target": "src/db/user.py"}], "external": []})
    grill.start_grill_session(WS)
    answer_all()
    tenets, _ = tree(store)
    by_name = {t["name"]: t for t in tenets.values()}
    # Auth uses the code in Db's "User" part, so it references it instead of duplicating its rules
    assert by_name["Auth"]["references"] == [by_name["User"]["id"]]
    assert all(t["references"] == [] for n, t in by_name.items() if n != "Auth")


def test_files_added_after_grilling_join_the_tree(store):
    grill.start_grill_session(WS)
    answer_all()
    later = FILES + ["src/auth/refresh.py", "billing/invoice.py"]
    res = pipeline.generate_requirements_and_tenets(store, {"files": [{"path": p} for p in later]}, "acme/legacy")
    tenets, _ = tree(store)
    owner = {l["path"]: t for t in tenets.values() for l in t["code_links"]}
    # a file next to existing code joins the leaf that owns that folder
    assert owner["src/auth/refresh.py"]["name"] in ("Session", "Token")
    # a new top-level folder becomes a new feature under the root, starting with a Hypothesis
    billing = owner["billing/invoice.py"]
    assert billing["name"] == "Billing" and not tenets[billing["parent_id"]]["parent_id"]
    assert res["created_tenets"] == [billing["id"]]
    started_with_one_hypothesis(store)
    for t in tenets.values():
        if t["children"]:
            assert t["code_links"] == []
    # running it again changes nothing
    again = pipeline.generate_requirements_and_tenets(store, {"files": [{"path": p} for p in later]}, "acme/legacy")
    assert again["created_tenets"] == [] and again["placed_files"] == {}
