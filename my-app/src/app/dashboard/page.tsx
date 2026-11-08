import { GhShell } from "@/gh/Shell";
import DashboardPage from "@/gh/DashboardPage";

export default function Page() {
  return (
    <GhShell>
      <DashboardPage />
    </GhShell>
  );
}
