import { Suspense } from "react";
import { GhShell } from "@/gh/Shell";
import RepoPage from "@/gh/RepoPage";

export default function Page({ params }: { params: Promise<{ owner: string; repo: string }> }) {
  return (
    <Suspense>
      <Inner params={params} />
    </Suspense>
  );
}

async function Inner({ params }: { params: Promise<{ owner: string; repo: string }> }) {
  const { owner, repo } = await params;
  return (
    <GhShell>
      <RepoPage owner={decodeURIComponent(owner)} repo={decodeURIComponent(repo)} />
    </GhShell>
  );
}
