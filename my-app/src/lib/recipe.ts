/** Test recipes are written as labelled parts (see the engine's Test Author contract). */
export const RECIPE_LABELS = [
  "ENV/SETUP", "FIXTURES", "ORDER", "INVOKE", "ASSERT", "EXPECTED", "TEARDOWN",
  "PASS WHEN", "FAIL WHEN", "INCONCLUSIVE WHEN", "LOCALIZE",
] as const;

export interface RecipePart {
  label: string;
  body: string;
  tone: "setup" | "act" | "check" | "pass" | "fail" | "inconclusive" | "plain";
}

const TONE: Record<string, RecipePart["tone"]> = {
  "ENV/SETUP": "setup", FIXTURES: "setup", ORDER: "setup", TEARDOWN: "setup",
  INVOKE: "act", ASSERT: "check", EXPECTED: "check", LOCALIZE: "check",
  "PASS WHEN": "pass", "FAIL WHEN": "fail", "INCONCLUSIVE WHEN": "inconclusive",
};

const LABEL_RE = new RegExp(`^\\s*(${RECIPE_LABELS.map((l) => l.replace("/", "\\/")).join("|")})\\s*[:\\-–]\\s*`, "i");

/** Splits a recipe into its labelled parts; unlabelled text becomes one "recipe" part. */
export function parseRecipe(text: string): RecipePart[] {
  const parts: RecipePart[] = [];
  let cur: RecipePart | null = null;
  for (const line of (text ?? "").split(/\r?\n/)) {
    const m = LABEL_RE.exec(line);
    if (m) {
      const label = m[1].toUpperCase();
      cur = { label, body: line.slice(m[0].length), tone: TONE[label] ?? "plain" };
      parts.push(cur);
    } else if (cur) cur.body += "\n" + line;
    else if (line.trim()) {
      cur = { label: "RECIPE", body: line, tone: "plain" };
      parts.push(cur);
    }
  }
  return parts.map((p) => ({ ...p, body: p.body.trim() })).filter((p) => p.body);
}

/** Which parts the spec requires that are missing (flags an under-specified recipe). */
export function missingParts(parts: RecipePart[]): string[] {
  const have = new Set(parts.map((p) => p.label));
  return ["INVOKE", "ASSERT", "EXPECTED", "PASS WHEN", "FAIL WHEN", "INCONCLUSIVE WHEN"].filter((l) => !have.has(l));
}
