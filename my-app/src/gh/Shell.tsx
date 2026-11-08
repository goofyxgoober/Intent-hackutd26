"use client";

import type { ReactNode } from "react";
import { AuthProvider, RequireAuth } from "./AuthContext";
import "./gh.css";

/** Scoped wrapper for the GitHub/intent-engine pages so their styles never touch the graph view. */
export function GhShell({ children, protectedRoute = true }: { children: ReactNode; protectedRoute?: boolean }) {
  return (
    <div className="gh">
      <AuthProvider>{protectedRoute ? <RequireAuth>{children}</RequireAuth> : children}</AuthProvider>
    </div>
  );
}
