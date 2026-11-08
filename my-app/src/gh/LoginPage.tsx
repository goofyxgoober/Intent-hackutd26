"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "./AuthContext";
import { TopBar } from "./Chrome";

const ERROR_MESSAGES: Record<string, string> = {
  access_denied: "authorization cancelled on github.com",
  invalid_state: "oauth state mismatch — session expired, try again",
  token_exchange_failed: "could not exchange code for access token",
  user_fetch_failed: "signed in, but GET /user failed",
  backend_offline: "FastAPI backend is offline — start it with 'npm run dev:api' on port 8000",
  "GITHUB_CLIENT_ID is not set in backend/.env": "GITHUB_CLIENT_ID is not set in backend/.env",
  "2fa_unknown":
    "GitHub didn't report whether two-factor authentication is on for this account. if it is on, ask whoever runs the backend to set REQUIRE_GITHUB_2FA=false",
  "2fa_required":
    "two-factor authentication is off on this GitHub account. turn it on in GitHub → Settings → Password and authentication, then sign in again",
};

function GitHubMark() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

/** A chalk scribble: the tangle of a legacy monolith becoming one clear arrow. */
function Tangle() {
  return (
    <figure className="tangle">
      <svg viewBox="0 0 260 110" width="200" height="85" aria-hidden="true">
        <g fill="none" stroke="var(--line)" strokeWidth="1.4" strokeDasharray="5 4">
          <ellipse cx="52" cy="52" rx="38" ry="40" transform="rotate(-12 52 52)" />
          <ellipse cx="82" cy="55" rx="24" ry="44" transform="rotate(14 82 55)" />
          <ellipse cx="108" cy="48" rx="34" ry="38" />
          <ellipse cx="132" cy="53" rx="26" ry="42" transform="rotate(-18 132 53)" />
        </g>
        <path d="M160 52 H245" stroke="var(--text)" strokeWidth="1.4" strokeDasharray="6 5" />
        <path d="M239 47 l8 5 -8 5" fill="var(--text)" />
      </svg>
      <figcaption>1,200 lines of tangle, one clear map</figcaption>
    </figure>
  );
}

export default function LoginPage() {
  const { user, loading, login } = useAuth();
  const params = useSearchParams();
  const router = useRouter();
  const error = params.get("error");

  useEffect(() => {
    if (!loading && user) {
      window.location.href = "/dashboard";
    }
  }, [loading, user]);

  return (
    <div className="app">
      <TopBar />
      <main className="login-canvas">
        <section className="login-card">
          <Tangle />
          <h1>Sign in to IntentFlow</h1>
          <p className="login-lede">
            Connect your GitHub account to map a repository into a graph of what the code does and the rules it must keep true.
          </p>
          {error ? (
            <p className="login-error" role="alert">
              Sign-in failed: {ERROR_MESSAGES[error] ?? error}
            </p>
          ) : null}
          <button className="btn primary login-btn" onClick={login} disabled={loading}>
            <GitHubMark /> Continue with GitHub
          </button>
          <p className="login-fine">IntentFlow requests read access to your repositories. Your token stays on the server.</p>
        </section>
      </main>
    </div>
  );
}
