# Intent-hackutd26

IntentFlow — intent-driven legacy codebase modernization (HackUTD '26).

## Login / GitHub OAuth (local dev)

1. Create a GitHub OAuth App at https://github.com/settings/developers
   - Homepage URL: `http://localhost:5173`
   - Authorization callback URL: `http://localhost:8000/auth/github/callback`
2. Backend:
   ```bash
   cd backend
   cp .env.example .env   # fill in GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```
3. Frontend:
   ```bash
   cd frontend
   npm install
   npm run dev            # http://localhost:5173
   ```

### Two-factor authentication
Sign-in is GitHub OAuth. GitHub asks for the user's 2FA code during login, and the
backend also rejects any account that doesn't have 2FA turned on
(`REQUIRE_GITHUB_2FA=true`, the default). Set it to `false` for test accounts.

### API
All `/api` routes need a signed-in session. Data is stored per user **and** per repo
in SQLite (`DATABASE_PATH`, default `backend/intentflow.db`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/github/login` | Redirects to GitHub (sets CSRF `state` cookie) |
| GET | `/auth/github/callback` | Exchanges code, checks 2FA, creates session |
| GET | `/auth/me` · POST `/auth/logout` | Current user · end session |
| GET | `/api/github/repos` | Repos the user can access |
| GET | `/api/github/repos/{owner}/{repo}/tree?ref=` | All file paths |
| GET | `/api/github/repos/{owner}/{repo}/file?path=&ref=` | One file's text |
| GET | `/api/github/repos/{owner}/{repo}/branches` | Branch names and head SHAs |
| GET | `/api/github/repos/{owner}/{repo}/commits?ref=&path=&limit=` | Commit history; `path` gives one file's history |
| GET | `/api/github/repos/{owner}/{repo}/commits/{sha}` | One commit with every changed file and its diff |
| GET | `/api/github/repos/{owner}/{repo}/compare?base=&head=` | Commits and file diffs between any two branches, tags or SHAs |
| GET | `/api/github/repos/{owner}/{repo}/diff?sha=` or `?base=&head=` | Full unified diff as text, for files GitHub leaves out of the JSON |
| GET | `/api/repos` | Repos this user connected |
| POST | `/api/repos/{owner}/{repo}/connect` | Connect a repo (checks access) |
| DELETE | `/api/repos/{owner}/{repo}` | Disconnect and delete its intents |
| GET | `/api/repos/{owner}/{repo}/changes` | Files modified since last sync + affected intents (read-only) |
| POST | `/api/repos/{owner}/{repo}/sync` | Accept current head; flags intents on modified files `stale` |
| GET | `/api/repos/{owner}/{repo}/activity` | File changes received by the webhook |
| GET | `/api/repos/{owner}/{repo}/intents?stale=&source_file=` | List intent nodes |
| GET | `/api/repos/{owner}/{repo}/intents/{node_id}/history` | Commits that touched the intent's source file |
| GET/PUT/DELETE | `/api/repos/{owner}/{repo}/intents/{node_id}` | Read / upsert / delete one node. PUT takes `?expected_version=` and returns 409 on a conflicting edit |
| GET/PUT | `/api/repos/{owner}/{repo}/graph` | Whole IntentGraph; PUT replaces it (for the intent engine) |
| POST | `/api/repos/{owner}/{repo}/intents/export` | Commit the graph to `.intentflow/intent_graph.json` on branch `intentflow/intents` |
| POST | `/webhooks/github` | GitHub push webhook (HMAC-verified) |

Changed files come back as `{path, previous_path, status, additions, deletions, patch, patch_truncated}`.
When `patch_truncated` is true GitHub skipped that file's diff (too large or binary); use `/diff`.
Refs and paths are validated so they can't reach other GitHub API routes.

Intent nodes follow the `IntentNode` schema in CONTEXT.md. `downstream_dependencies`
become `depends_on` edges automatically. Saving a node clears its `stale` flag.

### Push webhook (optional)
GitHub must reach your backend, so locally run `ngrok http 8000`, then in the repo's
**Settings → Webhooks → Add webhook** use `https://<ngrok-host>/webhooks/github`,
content type `application/json`, and the same secret as `GITHUB_WEBHOOK_SECRET`.
Without a webhook, **sync repo** still finds every change through the compare API.

### Tests
```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

The GitHub access token stays on the backend; the browser only holds an opaque
httpOnly session cookie.
