import { redirect } from "next/navigation";

// The graph view is the main page now; keep old links working.
export default function Graph() {
  redirect("/");
}
