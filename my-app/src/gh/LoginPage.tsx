"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "./AuthContext";
import { NodeCard, Stages, StatusBar, Terminal, TopBar } from "./Chrome";

const ERROR_MESSAGES: Record<string, string> = {
  access_denied: "authorization cancelled on github.com",
  invalid_state: "oauth state mismatch — session expired, try again",
  token_exchange_failed: "could not exchange code for access token",
  user_fetch_failed: "signed in, but GET /user failed",
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

/** The dashed "1,200 loc monolith tangle" scribble from the canvas. */
function Tangle() {
  return (
    <figure className="tangle">
      <svg viewBox="0 0 260 150" width="260" height="150" aria-hidden="true">
        <g fill="none" stroke="var(--line)" strokeWidth="1.4" strokeDasharray="5 4">
          <ellipse cx="62" cy="70" rx="48" ry="52" transform="rotate(-12 62 70)" />
          <ellipse cx="100" cy="74" rx="30" ry="58" transform="rotate(14 100 74)" />
          <ellipse cx="130" cy="64" rx="44" ry="50" />
          <ellipse cx="160" cy="70" rx="34" ry="56" transform="rotate(-18 160 70)" />
        </g>
        <path d="M150 70 H250" stroke="var(--text)" strokeWidth="1.4" strokeDasharray="6 5" />
        <path d="M244 65 l8 5 -8 5" fill="var(--text)" />
      </svg>
      <figcaption className="hand">1,200 loc monolith tangle</figcaption>
    </figure>
  );
}

export default function LoginPage() {
  const { user, loading, login } = useAuth();
  const params = useSearchParams();
  const router = useRouter();
  const error = params.get("error");

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  return (
    <div className="app">
      <TopBar right={<span className="hand dim">vast codebase canvas</span>} />
      <div className="subbar">
        <Stages active={1} />
        <div className="chips">
          <span className="chip">step 0 · authenticate</span>
        </div>
      </div>

      <main className="canvas login-canvas">
        <div className="login-graph">
          <Tangle />
          <NodeCard
            name="github_oauth"
            tag="src/auth/github"
            summary="Exchange a GitHub grant for a server-held session before any repo sync."
            className="login-node"
          >
            <div className="mono-list">
              <div>state mismatch → reject</div>
              <div>token never leaves backend</div>
            </div>
            <span className="link-purple">[scope: read:user repo]</span>
          </NodeCard>
        </div>

        <Terminal
          className="login-terminal"
          footer={
            <button className="cta" onClick={login} disabled={loading}>
              <span className="prompt">guest@intentflow:~$</span>
              <span className="cta-input">
                <GitHubMark /> auth --provider=github
              </span>
              <span className="enter">↵</span>
            </button>
          }
        >
          <div className="line">
            <span className="purple">⚡ DISTRO →</span> Arch Linux x86_64 ·{" "}
            <span className="purple">Nemotron 70B Agentic Core</span>
          </div>
          <div className="line dim">
            TARGET → <span className="text">not connected</span> · 0 AST nodes mapped
          </div>
          <div className="gap" />
          <div className="line">
            <span className="purple">guest@intentflow:~$</span> whoami
          </div>
          <div className="line dim">├ no session — connect GitHub to sync a repository</div>
          <div className="line dim">├ IntentFlow maps code into a Functional Intent Graph</div>
          <div className="line dim">└ flows, business rules &amp; invariants — not raw syntax</div>
          {error ? (
            <div className="line red" role="alert">
              ✗ auth failed: {ERROR_MESSAGES[error] ?? error}
            </div>
          ) : (
            <div className="line green">✓ ready. press ↵ to continue with GitHub.</div>
          )}
        </Terminal>
      </main>

      <StatusBar sync="Ayaan OAuth webhook" />
    </div>
  );
}
