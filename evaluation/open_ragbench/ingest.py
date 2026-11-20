"""
Index the Open RAGBench subset (gold + distractor papers) into an eval project
through the real ingestion pipeline, reading PDFs from local disk.

Run from server/:
    python -m evaluation.open_ragbench.ingest [--project-name evals] [--limit N] [--papers ID ...] [--workers 2]

Papers already `completed` in the project are skipped; any other existing row for a
paper is deleted (cascading its chunks) and the paper is indexed again.

Writes open_ragbench/data/ingest_runs/<project-name>.json and exits non-zero if any paper failed.
"""
import os

# Must happen before importing src, so summary-LLM traces go to a separate LangSmith project.
# load_dotenv does not override variables that are already set.
os.environ.setdefault("LANGSMITH_PROJECT", "knowledgedock-eval")

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.services.database import supabase
from src.rag.ingestion.index import process_document

from evaluation.config import EVAL_CLERK_ID, EVAL_PROJECT_NAME, EVAL_PROJECT_SETTINGS

DATA_DIR = Path(__file__).parent / "data"
PDF_DIR = DATA_DIR / "pdfs"
MANIFEST_PATH = DATA_DIR / "manifest.json"
RUNS_DIR = DATA_DIR / "ingest_runs"


def ensure_user(clerk_id: str) -> None:
    """Create the users row for the eval clerk_id if it doesn't exist."""
    existing = supabase.table("users").select("clerk_id").eq("clerk_id", clerk_id).execute()
    if existing.data:
        print(f"user exists: {clerk_id}")
        return
    supabase.table("users").insert({"clerk_id": clerk_id}).execute()
    print(f"user created: {clerk_id}")


def ensure_project(clerk_id: str, name: str, settings: dict) -> str:
    """Return the project id for (clerk_id, name), creating the project and its settings row if missing."""
    existing = (
        supabase.table("projects").select("id")
        .eq("clerk_id", clerk_id).eq("name", name).execute()
    )
    if existing.data:
        project_id = existing.data[0]["id"]
        print(f"project exists: {name} ({project_id})")
        return project_id

    project = supabase.table("projects").insert({
        "clerk_id": clerk_id,
        "name": name,
        "description": "Eval project (created by evaluation/open_ragbench/ingest.py)",
    }).execute()
    project_id = project.data[0]["id"]

    try:
        result = supabase.table("project_settings").insert({"project_id": project_id, **settings}).execute()
        if not result.data:
            raise RuntimeError("no data returned")
    except Exception:
        # Roll back, same as create_project
        supabase.table("projects").delete().eq("id", project_id).execute()
        raise

    print(f"project created: {name} ({project_id})")
    return project_id


def create_local_document(project_id: str, clerk_id: str, pdf_path: Path) -> str:
    """
    Insert a fresh project_documents row for a local PDF and return its id.
    An existing row with the same filename is deleted first (cascade removes its chunks).
    """
    filename = pdf_path.name
    existing = (
        supabase.table("project_documents").select("id")
        .eq("project_id", project_id).eq("filename", filename).execute()
    )
    for row in existing.data:
        supabase.table("project_documents").delete().eq("id", row["id"]).execute()
        print(f"deleted existing document row: {row['id']}")

    doc = supabase.table("project_documents").insert({
        "project_id": project_id,
        "filename": filename,
        "file_size": pdf_path.stat().st_size,
        "file_type": "application/pdf",
        "s3_key": f"local://open_ragbench/{filename}",
        "source_type": "file",
        "clerk_id": clerk_id,
    }).execute()
    document_id = doc.data[0]["id"]
    print(f"document row created: {filename} ({document_id})")
    return document_id


def select_papers(papers: list[str] | None, limit: int | None) -> list[tuple[str, str]]:
    """Return [(paper_id, role)], gold first so a trial run has questions to check."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    ordered = [(p, "gold") for p in manifest["papers"]["gold"]] + \
              [(p, "distractor") for p in manifest["papers"]["distractor"]]
    if papers:
        ordered = [(p, r) for p, r in ordered if p in set(papers)]
    if limit:
        ordered = ordered[:limit]
    return ordered


def find_document(project_id: str, filename: str) -> dict | None:
    rows = (
        supabase.table("project_documents").select("id, processing_status")
        .eq("project_id", project_id).eq("filename", filename).execute()
    ).data
    return rows[0] if rows else None


def document_stats(document_id: str) -> dict:
    """Status, elements_found and chunk counts (total / with table / with image) for one document."""
    doc = (
        supabase.table("project_documents").select("processing_status, processing_details")
        .eq("id", document_id).execute()
    ).data[0]
    types = [
        c["type"] or []
        for c in supabase.table("document_chunks").select("type").eq("document_id", document_id).execute().data
    ]
    details = doc["processing_details"] or {}
    return {
        "status": doc["processing_status"],
        "chunks": len(types),
        "chunks_with_table": sum("table" in t for t in types),
        "chunks_with_image": sum("image" in t for t in types),
        "elements_found": details.get("partitioning", {}).get("elements_found"),
    }


def ingest_paper(project_id: str, paper_id: str, role: str) -> dict:
    """Skip if completed, otherwise (re)create the document row and run the pipeline on the local PDF."""
    pdf_path = PDF_DIR / f"{paper_id}.pdf"
    result = {"paper_id": paper_id, "role": role, "seconds": None, "error": None}

    existing = find_document(project_id, pdf_path.name)
    if existing and existing["processing_status"] == "completed":
        return {**result, "document_id": existing["id"], "skipped": True, **document_stats(existing["id"])}

    # create_local_document deletes any non-completed row for this filename first
    document_id = create_local_document(project_id, EVAL_CLERK_ID, pdf_path)
    start = time.perf_counter()
    try:
        process_document(document_id, local_path=str(pdf_path))
    except Exception as e:
        result["error"] = str(e)
    result["seconds"] = round(time.perf_counter() - start, 1)
    return {**result, "document_id": document_id, "skipped": False, **document_stats(document_id)}


def main():
    parser = argparse.ArgumentParser(description="Index Open RAGBench papers into an eval project.")
    parser.add_argument("--project-name", default=EVAL_PROJECT_NAME)
    parser.add_argument("--limit", type=int, help="Only the first N papers (gold first)")
    parser.add_argument("--papers", nargs="+", metavar="ID", help="Specific paper ids")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    ensure_user(EVAL_CLERK_ID)
    project_id = ensure_project(EVAL_CLERK_ID, args.project_name, EVAL_PROJECT_SETTINGS)
    selected = select_papers(args.papers, args.limit)

    run_path = RUNS_DIR / f"{args.project_name}.json"
    previous = json.loads(run_path.read_text())["papers"] if run_path.exists() else {}

    print(f"\n{len(selected)} papers, {args.workers} workers, project {args.project_name} ({project_id})\n")
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(ingest_paper, project_id, p, r): p for p, r in selected}
        for i, fut in enumerate(as_completed(futures), 1):
            paper_id = futures[fut]
            try:
                res = fut.result()
            except Exception as e:  # failure outside process_document (e.g. DB insert); log and continue
                res = {"paper_id": paper_id, "status": "failed", "error": str(e)}
            if res.get("skipped"):
                # Keep the timing from the run that actually indexed this paper
                res["seconds"] = previous.get(paper_id, {}).get("seconds")
            results[paper_id] = res
            tag = "SKIP" if res.get("skipped") else ("FAIL" if res.get("error") else "OK  ")
            print(f"[{i}/{len(selected)}] {tag} {paper_id} ({res.get('role')}) "
                  f"status={res.get('status')} chunks={res.get('chunks')} seconds={res.get('seconds')}"
                  + (f"\n      error: {res['error']}" if res.get("error") else ""))

    failures = {p: r.get("error") for p, r in results.items() if r.get("status") != "completed"}
    done = [r for r in results.values() if r.get("status") == "completed"]
    secs = [r["seconds"] for r in done if r.get("seconds") is not None]

    run = {
        "project_id": project_id,
        "clerk_id": EVAL_CLERK_ID,
        "settings": EVAL_PROJECT_SETTINGS,
        "totals": {
            "papers": len(results),
            "completed": len(done),
            "failed": len(failures),
            "chunks": sum(r["chunks"] for r in done),
            "chunks_with_table": sum(r["chunks_with_table"] for r in done),
            "chunks_with_image": sum(r["chunks_with_image"] for r in done),
            "seconds_p50": round(statistics.median(secs), 1) if secs else None,
            "seconds_max": max(secs) if secs else None,
        },
        "failures": failures,
        "papers": dict(sorted(results.items())),
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_path.write_text(json.dumps(run, indent=2))

    print(f"\ntotals: {json.dumps(run['totals'])}")
    print(f"run file: {run_path}")
    if failures:
        print(f"FAILED: {sorted(failures)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
