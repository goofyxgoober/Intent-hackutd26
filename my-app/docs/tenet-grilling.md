# Tenet Grilling (Intent Builder)

Tenet grilling builds a repo's Tenet hierarchy by asking the developer questions, one level at a
time (spec 10.2). The pipeline makes a first rough tree from the code. Grilling then walks that
tree top-down, asks up to three confirm-or-correct questions per Tenet, and splits each Tenet into
children until it reaches the maximum depth.

```
system      Legacy                      level 0
feature     ├── Auth                    level 1
component   │   ├── Session             level 2
component   │   └── Token               level 2
feature     ├── Db                      level 1
feature     └── Web                     level 1
```

## Rules it follows

- **Every Tenet starts with a Hypothesis.** The root, the features made by the pipeline and every
  Tenet created during grilling get one starting Hypothesis, taken from their own code. Users are
  never required to make an Axiom; promoting a Hypothesis to an Axiom is always the developer's choice.
- **Level by level.** Tenets are grilled breadth-first: the whole system, then every feature, then
  every component, then behaviours. A level is settled before the next one starts.
- **At most 3 questions per Tenet**, phrased as "I think ... Is that right?".
- **Answers are kept verbatim.** A typed correction replaces the draft word for word. A rule typed
  in answer to "What must X always guarantee?" becomes a Hypothesis in the developer's own words.
- **"Don't know" never blocks.** It is recorded in the session's `unknowns` and grilling moves on.
- **The developer can refuse a split.** Answering "No" to "I'd split X into ..." keeps X as one leaf.
- **No fake tests.** Grilling writes `test_implementation: ""`; the Test Author writes test recipes.
- **Code links live on leaves only.** When a Tenet is split, its files move to its children, and
  every file stays covered by exactly one leaf.
- **Composition, not duplication.** When a Tenet's code imports code owned under one of its peers,
  it gets a reference to that Tenet instead of repeating its rules (`add_composition_references`).
- **New code keeps getting covered.** Files added in later commits join the leaf that owns their
  folder; a new top-level folder becomes a new feature with a starting Hypothesis
  (`place_new_files`). This runs on every sync and pipeline run, and never rebuilds a grilled tree.

## Running it

From `my-app/`, with `backend/.env` filled in (see `backend/.env.example`):

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm install
npm run dev:all
```

Open http://localhost:3000/login, sign in with GitHub, open a repo and sync it. The sync runs the
pipeline, which builds the first tree and starts a grilling session at the root.

## Using it (terminal panel)

| Command | What it does |
| --- | --- |
| `grill` | Show the current Tenet, its level and the open question |
| `grill start` | Start over from the root |
| `grill answer A` | Pick option A (also `b`, `[c]`, `option B`, `2`) |
| `grill answer <text>` | Answer in your own words; kept exactly as typed |
| `grill skip` | "Don't know"; recorded and skipped |

An answer that only starts with the word "A" ("A billing system that ...") is kept as text, not
read as option A.

## API

All routes need a signed-in session and a connected repo.

| Method | Route | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/repos/{owner}/{repo}/grill` | none | Status: `active`, `tenet_name`, `level`, `level_name`, `current_question`, `answered_count`, `total_questions`, `queue_remaining`, `done` |
| POST | `/api/repos/{owner}/{repo}/grill/start` | `{"tenet_id": null}` (optional; root by default) | The new session, with its first questions |
| POST | `/api/repos/{owner}/{repo}/grill/answer` | `{"answer": "A", "question_id": null, "dont_know": false}` | `recorded_answer`, `next_question`, `next_tenet_name`, `created_tenets`, `created_hypotheses`, `level`, `done` |

WebSocket events: `grill.question` (a new Tenet's questions are ready), `grill.tenet_done` (a
Tenet was finalized, with its new children and Hypotheses), `grill.done` (the whole tree is done)
and `graph.refresh`.

Re-running the pipeline (the terminal does this after answers) resumes the active session instead
of restarting it. Only `grill start` starts over.

## How it works (code map)

Everything is in `backend/app/grill.py` unless noted.

1. **First tree** (`pipeline.generate_requirements_and_tenets`). Groups the repo's files by top
   folder into features under a root named after the repo, links every file to its feature, and
   calls `ensure_hypothesis` on each. With an NVIDIA key, `_name_features` asks Nemotron once for
   feature names and descriptions.
2. **Start** (`start_grill_session`). Makes sure a root exists (`_ensure_root`), then enters the
   first Tenet (`_enter_tenet`). The session is saved to
   `data/workspaces/<id>/intent/.sessions/grill_ws_<id>.json`.
3. **Questions** (`generate_questions_for_tenet`). Builds context from the Tenet's files and their
   annotations (`_scope_files`, `_code_context`) and from earlier answers for its ancestors
   (`_prior_answers`), then asks the LLM for a draft plus up to 3 questions. Without a key it asks:
   - "I think X does this: ... Is that right?"
   - "I'd split X into N parts: ..." (only when X can still be split)
   - "What must X always guarantee, no matter how the code changes?"
4. **Answers** (`submit_grill_answer`). Records each answer verbatim (`resolve_option_choice` maps
   letters to options). After the last question of a Tenet it calls `finalize_tenet`.
5. **Finalize** (`finalize_tenet`). Updates the functionality from the answers, adds up to 3
   Hypotheses, and splits the Tenet into children. The LLM proposes the parts; without a key,
   `_structural_split` splits at the first folder where the files diverge, keeps config and docs
   files with the code, and names generic folders (`src`, `lib`, ...) after the parent.
   `_apply_children` moves the code links to the children and gives each one a starting Hypothesis.
6. **References.** After a split, `add_composition_references` walks the import edges: if code
   under a Tenet imports a file owned under one of its peers, the Tenet references the part of
   that peer that owns the file (REFERENCE_SCOPE=peer_children). Pairs that would make a cycle are
   skipped. The `grill.tenet_done` event lists the references added.
7. **Next Tenet.** The children are queued, and the next queued Tenet is entered. When the queue
   is empty the session is `done`.
8. **Later commits.** `place_new_files` runs from `generate_requirements_and_tenets` (when a tree
   already exists) and from incremental syncs (`sync.py`, for added files). Each file joins the
   leaf whose files share the longest folder path; otherwise its top folder becomes a new feature.
   The sync batch lists them under `placed_files` and `created_tenets`. A hand-made tree with no
   code links at all is left alone.

Starting Hypotheses come from `default_hypothesis`, in this order: a rule the code enforces (from
annotations), the code's responsibilities, the Tenet's functionality, then its file paths. A Tenet
with children gets "X combines A, B and C to provide its behaviour."

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `INTENT_MAX_DEPTH` | `3` | Deepest level grilling creates (0 system, 1 feature, 2 component, 3 behavior) |
| `NVIDIA_API_KEY` | none | Turns on Nemotron questions, drafts and splits; without it the code-based fallback runs |

## Tests

```bash
cd my-app
NVIDIA_API_KEY= python3 -m pytest -q backend/tests/test_grill.py
```

`backend/tests/test_grill.py` covers level ordering, splits, links on leaves, starting
Hypotheses, verbatim answers, corrections, one-word replies, "don't know", refused splits, max
depth, the LLM path (scripted), old session files, resuming after a pipeline run, composition
references from imports and files added after grilling. Tests replace
`grill._llm_json`, so they run offline.

## Extending it

- **Better questions or splits:** change the prompts in `generate_questions_for_tenet` and
  `finalize_tenet`. Keep the JSON shapes they ask for; the parsing code depends on them.
- **Another LLM:** replace `_llm_json(system, prompt)`. It must return a dict or `None`; `None`
  falls back to the code-based questions.
- **A UI for grilling:** use the three API routes above and listen for the `grill.*` events.
- **Do not** set a Claim to `axiom` from grilling or write test recipes there; both belong to the
  developer and the Test Author.
