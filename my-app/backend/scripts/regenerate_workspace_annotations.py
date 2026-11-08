"""Re-annotate a workspace's repo with Nemotron and rebuild its tenets and claims.

Usage (from my-app/):
    python3 backend/scripts/regenerate_workspace_annotations.py <workspace_id>

The workspace id is shown by GET /api/repos (field "id"); the repo name is read
from the database, so nothing here is tied to a particular GitHub account.
"""
import argparse
import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app import db
from app.intent.store import IntentStore
from app.pipeline import (
    generate_annotations_for_file,
    generate_requirements_and_tenets,
    start_tenet_grilling_session,
)

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("workspace_id", type=int, help="workspace (connected repo) id")
args = parser.parse_args()

ws_id = args.workspace_id
with db.connect() as conn:
    row = conn.execute("SELECT full_name FROM repos WHERE id = ?", (ws_id,)).fetchone()
if row is None:
    sys.exit(f"No workspace {ws_id}. Connect the repo in the app first; GET /api/repos lists ids.")
repo_full_name = row["full_name"]
print(f"Workspace {ws_id}: {repo_full_name}")

ws_dir = backend_dir.parent / "data" / "workspaces" / str(ws_id)
repo_dir = ws_dir / "repo"
intent_dir = ws_dir / "intent"

print(f"Reading files from: {repo_dir}")
sources = {}
files_list = []
for p in repo_dir.rglob("*"):
    if p.is_file():
        rel = str(p.relative_to(repo_dir))
        content = p.read_text(encoding="utf-8", errors="replace")
        sources[rel] = content
        files_list.append({"path": rel, "size": len(content)})

print(f"Found {len(sources)} files in repository")

annot_dir = intent_dir / "annotations"
annot_dir.mkdir(parents=True, exist_ok=True)
for f in annot_dir.glob("**/*.json"):
    f.unlink()

def process_file(item):
    rel, content = item
    print(f"Starting Nemotron synthesis for: {rel}")
    annot = generate_annotations_for_file(rel, content)
    out_file = annot_dir / f"{rel}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(annot, indent=2), encoding="utf-8")
    purpose_preview = annot["summary"]["purpose"][:60].replace("\n", " ")
    print(f"✓ Finished {rel} -> {purpose_preview}...")
    return rel, annot

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(process_file, (rel, content)) for rel, content in sorted(sources.items())]
    for future in as_completed(futures):
        rel, annot = future.result()

print(f"\nWrote all detailed annotations to {annot_dir}")

# 2. Reset tenets, claims, links, spec
for sub in ["tenets", "claims", "links", "spec"]:
    d = intent_dir / sub
    if d.exists():
        import shutil
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

# 3. Generate requirements, tenets, claims, spec
store = IntentStore(ws_id)
snapshot = {"files": files_list}
res = generate_requirements_and_tenets(store, snapshot, repo_full_name, sources)
print(f"Created {len(res.get('created_tenets', []))} tenets")
print(f"Created {len(res.get('created_claims', []))} claims")

# 4. Start grilling session
grill_state = start_tenet_grilling_session(ws_id, store, res["root_id"], repo_full_name)
print(f"Started grilling session: {grill_state['id']} with {len(grill_state['questions'])} questions")

print("\n=== SUCCESSFUL PARALLEL REGENERATION COMPLETE ===")
