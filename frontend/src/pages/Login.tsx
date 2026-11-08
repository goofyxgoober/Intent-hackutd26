import { Navigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const ERROR_MESSAGES: Record<string, string> = {
  access_denied: "GitHub authorization was cancelled.",
  invalid_state: "Your sign-in session expired. Please try again.",
  token_exchange_failed: "Couldn't complete sign-in with GitHub. Please try again.",
  user_fetch_failed: "Signed in, but couldn't load your GitHub profile.",
};

function GitHubMark() {
  return (
    <svg viewBox="0 0 16 16" width="20" height="20" aria-hidden="true" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

export default function Login() {
  const { user, loading, login } = useAuth();
  const [params] = useSearchParams();
  const error = params.get("error");

  if (!loading && user) return <Navigate to="/dashboard" replace />;

  return (
    <main className="login">
      <section className="login-card">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <span>IntentFlow</span>
        </div>
        <h1>Modernize legacy code by intent</h1>
        <p className="muted">
          Connect GitHub to map your repository into a Functional Intent Graph — business rules,
          flows and invariants instead of raw syntax.
        </p>

        {error && (
          <div className="alert" role="alert">
            {ERROR_MESSAGES[error] ?? "Sign-in failed. Please try again."}
          </div>
        )}

        <button className="btn-github" onClick={login} disabled={loading}>
          <GitHubMark />
          Continue with GitHub
        </button>

        <p className="fine-print">
          We request read access to your profile and repositories so IntentFlow can sync and parse
          the code you choose.
        </p>
      </section>
    </main>
  );
}
