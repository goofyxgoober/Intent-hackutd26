# Intent-hackutd26

IntentFlow — intent-driven legacy codebase modernization (HackUTD '26).

## Login / GitHub OAuth (local dev)

Everything lives in this folder: the Next.js frontend (`src/`), the FastAPI backend (`backend/`)
and the intent engine package (`intentflow/`).

1. Create a GitHub OAuth App at https://github.com/settings/developers
   - Homepage URL: `http://localhost:3000`
   - Authorization callback URL: `http://localhost:8000/auth/github/callback`
2. Backend (from this folder):
   ```bash
   cp backend/.env.example backend/.env   # fill in GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET
   pip install -r backend/requirements.txt
   npm run dev:api                        # http://localhost:8000
   ```
3. Frontend:
   ```bash
   cp .env.example .env.local
   npm install
   npm run dev                            # http://localhost:3000
   ```
   Routes: `/` (intent graph + terminal), `/login`, `/dashboard` (repo picker), `/repos/:owner/:repo` (sync, history, tenets).
4. Tests: `npm run test:api` (pytest, see `pytest.ini`).

### Two-factor authentication
Sign-in is GitHub OAuth. GitHub asks for the user's 2FA code during login, and the
backend also rejects any account that doesn't have 2FA turned on
(`REQUIRE_GITHUB_2FA=true`, the default). Set it to `false` for test accounts.
If 2FA is off, the login page says `2fa_required`; if GitHub didn't report the status at all, it
says `2fa_unknown`. Every failed sign-in is also logged in the backend terminal with the reason.

## Intent engine backend (spec: IntentFlow Intent Engine Specification)

The backend owns the intent folder and enforces the spec's non-negotiable rules
(section 3) and permission matrix (section 7). Rules are checked in
`backend/app/intent/store.py`, never left to prompts.

### Who is calling
| Caller | How | Can |
|---|---|---|
| User | GitHub session cookie | Everything a user can in section 7; the only one who promotes, demotes, hand-edits Axioms, dismisses flags, exports |
| `builder` agent (Intent Builder, Test Author, Remake) | `Authorization: Bearer <key>` | Create/edit Tenets and Hypotheses, add references, scrap and remake. Never touches Axioms |
| `test_runner` agent | `Authorization: Bearer <key>` | Append results only |
| `engine` agent (Annotator, Jev, link builder, Spec Compiler) | `Authorization: Bearer <key>` | Code links, annotations, spec, Jev verdicts, Tenet edits |

Keys come from `AGENT_KEYS` in `backend/.env`. Agents may send `X-Agent-Name` for provenance.

### Storage
Each connected repo is a **workspace** (its id is returned by `/api/repos/{owner}/{repo}/connect`).
Its intent folder lives at `backend/data/workspaces/<id>/intent/` with the section 6 layout
(`tenets/`, `claims/`, `results/`, `annotations/`, `links/`, `history/`, `spec/`, `changelog/`).
**Export** commits it to `.intentflow/` on the `intentflow/intents` branch, with Tenets in nested
folders mirroring ownership and `results/` gitignored. It never writes to the default branch.

### Workspace API (`/api/workspaces/{id}`)
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/tree` | all | Tenets with level, leaf flag, A/H counts, roll-up verdict, flags; all live Claims with result summaries |
| POST | `/tenets` | user, builder, engine | Create a Tenet (`parent_id` null = root; only one root) |
| GET/PATCH/DELETE | `/tenets/{id}` | user, builder, engine | Read (with footprint) / edit name, functionality, child order, cross-cutting / delete (refused if it holds Axioms, has children, or is referenced) |
| POST | `/tenets/{id}/move` | user, builder, engine | New parent; Claims untouched |
| POST/DELETE | `/tenets/{id}/references[/{target}]` | user, builder, engine | Composition references; cycles rejected; `REFERENCE_SCOPE` limits targets |
| PUT | `/tenets/{id}/links` | engine | Code links (leaves only) |
| GET | `/tenets/{id}/rejected` | all | Rejected interpretations for the Remake Agent |
| POST | `/tenets/{id}/claims` | user, builder, engine | New Hypothesis |
| GET/PATCH | `/claims/{id}` | all / user, builder, engine | Read / edit a Hypothesis (Axioms refused) |
| PUT | `/claims/{id}/axiom` | user | Hand edit with `acknowledge_warning` + `reason`; 428 returns the impact summary first |
| GET | `/claims/{id}/impact` | all | Demotion/edit ripple: dependents, integration Claims above, referencing Tenets, linked code, stale results, provisional spec sections |
| POST | `/claims/{id}/promote` | user | Needs a passing, non-flaky result for the current wording and passing/locked dependencies; or `accept_without_verification` (badged) |
| POST | `/claims/{id}/demote` | user | Reason required; snapshots, flags dependents, stales their results |
| POST | `/claims/{id}/scrap`, `/remake` | user, builder | Scrap Hypotheses (never Axioms); remake must differ from rejected readings |
| DELETE | `/claims/{id}/flags/{kind}` | user | Dismiss a flag |
| POST/GET | `/claims/{id}/results` | test_runner / all | Append-only runs bound to `claim_hash`; send `code_ref` for the determinism check |
| GET/PUT | `/annotations?path=` | all / engine | Annotator output per file |
| GET/PUT | `/spec` | all / engine | Compiled spec |
| POST | `/jev/verdicts` | engine | Typed Jev output; unknown ids rejected; `update_existing` on an Axiom rejected; `axiom_conflict` flags Axioms |
| GET | `/codebase` | all | Folder tree, files (annotated?, constraining Tenets), import edges, external packages |
| GET | `/sync/batches[/{id}]` | all | Debounced push batches: changed files, renames, affected Tenets, Claims to re-run, orphans |
| GET | `/inbox`, `/changelog`, `/history?kind=` | all | Review inbox, decision log, snapshots |
| POST | `/export` | user | Commit the intent folder to `intentflow/intents` |
| WS | `/ws/workspaces/{id}` | all (`?key=` for agents) | Live events: `tenet.*`, `claim.*`, `result.appended`, `sync.batch`, `jev.verdict`, ... |

### Errors
Every error response is `{"detail": ..., "code": "..."}`. Codes the chat layer branches on:
`AXIOM_LOCKED`, `NOT_VERIFIED`, `DEPENDENCY_NOT_READY` (`detail.blockers` lists the Claims),
`PERMISSION_DENIED`, `UNAUTHENTICATED`, `NOT_FOUND`, `VALIDATION`, `CONFLICT`,
`CONFIRMATION_REQUIRED` (Axiom hand edit without the warning acknowledged), `RATE_LIMITED`, `GITHUB_ERROR`.

### Live events
`flag.raised` (`claim_id`, `tenet_id`, `status`, `kind`, `reason`) fires whenever a Claim is
flagged: a failing Axiom test, a Jev conflict, or a demoted or edited dependency. Nothing changes
automatically; the user decides.

### Git sync
**Polling (default, works locally):** while you have a repo open, the backend checks its default
branch every `POLL_INTERVAL_SECONDS` (30). When the head commit moves, it syncs. It stops after
`POLL_IDLE_STOP_SECONDS` without use and restarts when you come back. The repo page's
**changes** tab shows the latest change live: commits, files, and the exact line numbers added
and removed (`changed_lines`), with the diff a click away. `GET /api/workspaces/{id}/sync/status`
reports polling state; `GET …/sync/latest` returns the latest change; `POST …/sync/check` polls now.

**Webhooks (optional):** pushes to the default branch arrive by webhook, wait `SYNC_DEBOUNCE_SECONDS` for more, then
become one batch.

Either way, each batch: the codebase snapshot (file tree + import edges) updates first, renames carry
annotations and links, and the batch lists affected Tenets (leaf links propagated up through
owners and references) and Claims to re-test. Jev reviews it via `/jev/verdicts` with `batch_id`.
The last-synced commit is the diff base, so force pushes need no replay. **sync repo** does the
same on demand. GitHub tokens are held in memory only.

### Other routes
| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/github/login` · `/auth/github/callback` · `/auth/me` · POST `/auth/logout` | Sign-in |
| GET | `/api/github/repos[/{owner}/{repo}/…]` | Repos, branches, tree, file, commits, commit detail, compare, raw diff |
| GET/POST/DELETE | `/api/repos[/{owner}/{repo}[/connect\|/changes\|/sync]]` | Connect a repo (= workspace), preview changes, sync |
| POST | `/webhooks/github` | GitHub push webhook (HMAC-verified) |

### Push webhook (optional)
GitHub must reach your backend, so locally run `ngrok http 8000`, then in the repo's
**Settings → Webhooks → Add webhook** use `https://<ngrok-host>/webhooks/github`,
content type `application/json`, and the same secret as `GITHUB_WEBHOOK_SECRET`.
Without a webhook, **sync repo** does the same work on demand.

### Tests
```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```
