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

### Auth endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/github/login` | Redirects to GitHub (sets CSRF `state` cookie) |
| GET | `/auth/github/callback` | Exchanges code, creates session, redirects to `/dashboard` |
| GET | `/auth/me` | Current user, or 401 |
| POST | `/auth/logout` | Ends session |
| GET | `/api/github/repos` | Repos the signed-in user can access |

The GitHub access token stays on the backend (in-memory session store); the
browser only holds an opaque httpOnly session cookie. Other services can
protect routes with `Depends(require_session)` from `app.auth` and use
`session.access_token` to call GitHub.
