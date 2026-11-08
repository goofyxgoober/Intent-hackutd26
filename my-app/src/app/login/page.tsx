import { Suspense } from "react";
import { GhShell } from "@/gh/Shell";
import LoginPage from "@/gh/LoginPage";

export default function Page() {
  return (
    <Suspense>
      <GhShell protectedRoute={false}>
        <LoginPage />
      </GhShell>
    </Suspense>
  );
}
