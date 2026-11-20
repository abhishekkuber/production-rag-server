"""Download a seeded subset of Open RAGBench (vectara/open_ragbench, arXiv split).

Usage (from server/):
    python evaluation/open_ragbench/download.py
    python evaluation/open_ragbench/download.py --gold 5 --distractors 5 --held-out 2   # small trial

Picks three groups of papers with a fixed seed:
    gold        - indexed; their questions are the answerable eval questions
    distractor  - indexed; no questions point at them (the dataset's hard negatives)
    held_out    - NOT indexed; some of their questions become unanswerable (expected: refusal)

Writes to evaluation/open_ragbench/data/:
    raw/        the four dataset JSON files, as downloaded
    pdfs/       original arXiv PDFs for gold + distractor papers (what we ingest)
    corpus/     the dataset's own parsed JSON for gold papers (only used to match gold sections to chunks)
    questions.jsonl, manifest.json

Safe to re-run: files that already exist are skipped. Same args + seed give the same subset.
"""

import argparse
import hashlib
import json
import random
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

HF_BASE = "https://huggingface.co/datasets/vectara/open_ragbench/resolve/main/pdf/arxiv"
RAW_FILES = ["queries", "answers", "qrels", "pdf_urls"]
USER_AGENT = "knowledgedock-eval/0.1 (research benchmark download)"
# arXiv asks automated clients to keep to about one request every 3 seconds
ARXIV_DELAY_SECONDS = 3

OUT_DIR = Path(__file__).resolve().parent / "data"


def fetch(url: str, path: Path) -> bool:
    """Download url to path unless it already exists. Returns True if a request was made."""
    if path.exists() and path.stat().st_size > 0:
        return False
    tmp = path.with_suffix(path.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        tmp.write_bytes(resp.read())
    tmp.rename(path)
    return True


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_raw() -> dict:
    raw_dir = OUT_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    data = {}
    for name in RAW_FILES:
        path = raw_dir / f"{name}.json"
        fetch(f"{HF_BASE}/{name}.json", path)
        data[name] = json.loads(path.read_text())
    return data


def select_papers(data: dict, args, rng: random.Random) -> dict:
    questions_by_paper = defaultdict(list)
    for qid, qrel in data["qrels"].items():
        questions_by_paper[qrel["doc_id"]].append(qid)

    def has_table(paper_id):
        return any("table" in data["queries"][q]["source"] for q in questions_by_paper[paper_id])

    # Only papers with enough questions are worth indexing as gold; sort before shuffling so the seed is stable
    candidates = sorted(p for p, qs in questions_by_paper.items() if len(qs) >= args.min_questions)
    rng.shuffle(candidates)
    with_tables = [p for p in candidates if has_table(p)]
    without_tables = [p for p in candidates if not has_table(p)]

    # Over-sample papers with table questions: tables are only ~12% of the dataset but are the hard case
    n_table = round(args.gold * args.table_fraction)
    gold = with_tables[:n_table] + without_tables[: args.gold - n_table]
    remaining = [p for p in candidates if p not in gold]
    held_out = remaining[: args.held_out]

    negatives = sorted(set(data["pdf_urls"]) - set(questions_by_paper))
    rng.shuffle(negatives)
    distractors = negatives[: args.distractors]

    return {
        "gold": sorted(gold),
        "distractor": sorted(distractors),
        "held_out": sorted(held_out),
        "questions_by_paper": questions_by_paper,
    }


def build_questions(data: dict, papers: dict, args, rng: random.Random) -> list[dict]:
    def row(qid, answer_type):
        query, qrel = data["queries"][qid], data["qrels"][qid]
        return {
            "id": qid,
            "question": query["query"],
            "reference_answer": data["answers"][qid],
            "type": query["type"],
            "source": query["source"],
            "gold_doc": qrel["doc_id"],
            "gold_section": qrel["section_id"],
            "answer_type": answer_type,
        }

    rows = [row(q, "text") for p in papers["gold"] for q in sorted(papers["questions_by_paper"][p])]

    held_out_qids = sorted(q for p in papers["held_out"] for q in papers["questions_by_paper"][p])
    rng.shuffle(held_out_qids)
    for qid in held_out_qids[: args.unanswerable]:
        r = row(qid, "refusal")
        # The paper is not indexed, so the dataset's answer is not the expected one
        r["reference_answer"] = None
        r["gold_section"] = None
        rows.append(r)

    # Stratified dev/test split by (answer_type, source)
    strata = defaultdict(list)
    for r in rows:
        strata[(r["answer_type"], r["source"])].append(r)
    for key in sorted(strata):
        group = strata[key]
        rng.shuffle(group)
        n_dev = round(len(group) * args.dev_fraction)
        for i, r in enumerate(group):
            r["split"] = "dev" if i < n_dev else "test"

    return sorted(rows, key=lambda r: (r["gold_doc"], r["id"]))


def download_papers(data: dict, papers: dict) -> tuple[dict, list[str]]:
    pdf_dir, corpus_dir = OUT_DIR / "pdfs", OUT_DIR / "corpus"
    pdf_dir.mkdir(exist_ok=True)
    corpus_dir.mkdir(exist_ok=True)

    files, failures = {}, []
    to_index = [(p, "gold") for p in papers["gold"]] + [(p, "distractor") for p in papers["distractor"]]
    for i, (paper_id, role) in enumerate(to_index, 1):
        pdf_path = pdf_dir / f"{paper_id}.pdf"
        try:
            if fetch(data["pdf_urls"][paper_id], pdf_path):
                time.sleep(ARXIV_DELAY_SECONDS)
            if pdf_path.read_bytes()[:5] != b"%PDF-":
                pdf_path.unlink()
                raise ValueError("downloaded file is not a PDF")
            entry = {"pdf": pdf_path.name, "pdf_sha256": sha256(pdf_path), "pdf_bytes": pdf_path.stat().st_size}

            if role == "gold":
                corpus_path = corpus_dir / f"{paper_id}.json"
                fetch(f"{HF_BASE}/corpus/{paper_id}.json", corpus_path)
                entry["corpus"] = corpus_path.name
                entry["corpus_sha256"] = sha256(corpus_path)

            files[paper_id] = entry
            print(f"  [{i}/{len(to_index)}] ok      {role:<10} {paper_id} ({entry['pdf_bytes'] / 1e6:.1f} MB)")
        except Exception as e:
            failures.append(paper_id)
            print(f"  [{i}/{len(to_index)}] FAILED  {role:<10} {paper_id}: {e}")
    return files, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=int, default=20, help="papers whose questions are answerable")
    parser.add_argument("--distractors", type=int, default=20, help="hard-negative papers to index")
    parser.add_argument("--held-out", type=int, default=5, help="gold papers left out of the index")
    parser.add_argument("--unanswerable", type=int, default=20, help="questions sampled from held-out papers")
    parser.add_argument("--min-questions", type=int, default=5, help="min questions for a paper to be picked as gold")
    parser.add_argument("--table-fraction", type=float, default=0.5, help="share of gold papers with table questions")
    parser.add_argument("--dev-fraction", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    rng = random.Random(args.seed)

    print("Fetching dataset JSON files")
    data = load_raw()
    papers = select_papers(data, args, rng)
    questions = build_questions(data, papers, args, rng)

    print(f"Downloading {len(papers['gold'])} gold + {len(papers['distractor'])} distractor papers")
    files, failures = download_papers(data, papers)

    with (OUT_DIR / "questions.jsonl").open("w") as f:
        for q in questions:
            f.write(json.dumps(q) + "\n")

    manifest = {
        "dataset": "vectara/open_ragbench (pdf/arxiv)",
        "license": "cc-by-nc-4.0",
        "args": vars(args),
        "papers": {role: papers[role] for role in ("gold", "distractor", "held_out")},
        "files": files,
        "failed": failures,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))

    counts = defaultdict(int)
    for q in questions:
        counts[(q["split"], q["answer_type"])] += 1
    print(f"\n{len(questions)} questions: " + ", ".join(f"{s}/{t}={n}" for (s, t), n in sorted(counts.items())))
    print(f"{len(files)} papers ok, {len(failures)} failed")
    if failures:
        print("Failed:", ", ".join(failures))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
