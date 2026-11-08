import os
import json
import re
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("my-app/.env")
load_dotenv(".env")

NVIDIA_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

def call_nemotron(messages, max_tokens=2048):
    if not NVIDIA_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {NVIDIA_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": NVIDIA_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1
    }
    try:
        resp = requests.post(BASE_URL, headers=headers, json=payload, timeout=45)
        if resp.status_code == 200:
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content")
            if not content:
                # Fall back to reasoning_content if content was truncated by length
                reasoning = msg.get("reasoning_content") or ""
                # Attempt to extract json from reasoning if model put it there
                if "{" in reasoning and "}" in reasoning:
                    content = reasoning[reasoning.find("{"):reasoning.rfind("}") + 1]
            return content
        else:
            print(f"Nemotron error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"Nemotron exception: {e}")
    return None

def annotate_file_with_nemotron(file_path: str, content: str) -> dict:
    prompt = f"""You are the NVIDIA Nemotron Architectural Intent Engine.
Analyze this source code file ({file_path}) from a DAG task planning and visualization application.

SOURCE CODE:
{content}

Synthesize a comprehensive architectural annotation conforming strictly to this JSON format:
{{
  "purpose": "A detailed 2-3 sentence explanation of the file's architectural role, its operational boundaries, and its exact function in the DAG planner system.",
  "responsibilities": [
    "Detailed responsibility 1 (specific functions/classes, parameters, state updates)",
    "Detailed responsibility 2",
    "Detailed responsibility 3",
    "Detailed responsibility 4"
  ],
  "invariants": [
    "Strict, non-negotiable architectural invariant 1",
    "Strict, non-negotiable architectural invariant 2",
    "Strict, non-negotiable architectural invariant 3"
  ],
  "dependencies": ["imported_package_or_module_1", "imported_package_or_module_2"],
  "sections": ["Logical section 1", "Logical section 2", "Logical section 3"]
}}

Respond ONLY with the JSON object. Do not wrap in markdown quotes if possible."""

    messages = [
        {"role": "system", "content": "You are an expert system architect and invariant analyst. Output valid JSON only."},
        {"role": "user", "content": prompt}
    ]
    raw = call_nemotron(messages, max_tokens=2500)
    if raw:
        try:
            clean = raw.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            return json.loads(clean)
        except Exception as e:
            print(f"Failed to parse Nemotron response as JSON for {file_path}: {e}")
    return None

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Annotate one source file with Nemotron and print the result.",
        epilog="Example: python3 backend/scripts/test_nemotron_annotator.py src/app.ts --repo-dir data/workspaces/3/repo",
    )
    parser.add_argument("path", help="file path inside the repo, e.g. src/layout/Graph.tsx")
    parser.add_argument("--repo-dir", default=".", help="folder the path is relative to (default: current folder)")
    args = parser.parse_args()
    test_content = (Path(args.repo_dir) / args.path).read_text(encoding="utf-8")
    result = annotate_file_with_nemotron(args.path, test_content)
    print("RESULT:")
    print(json.dumps(result, indent=2))
