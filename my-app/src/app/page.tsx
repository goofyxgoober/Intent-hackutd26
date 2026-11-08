"use client";

import dynamic from "next/dynamic";

// React Flow + window-dependent config → render on the client only.
const Dashboard = dynamic(() => import("@/components/Dashboard"), { ssr: false });

export default function GraphPage() {
  return <Dashboard />;
}
