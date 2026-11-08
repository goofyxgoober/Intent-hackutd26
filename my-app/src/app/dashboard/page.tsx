"use client";

import dynamic from "next/dynamic";
import { GhShell } from "@/gh/Shell";

const DashboardPage = dynamic(() => import("@/gh/DashboardPage"), { ssr: false });

export default function Page() {
  return (
    <GhShell>
      <DashboardPage />
    </GhShell>
  );
}
