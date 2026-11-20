"""
Match each answerable question's gold section (Open RAGBench labels by section) to the
chunks our ingestion produced, so retrieval metrics can be computed per chunk.

A chunk is gold for a question if it contains at least `threshold` of the gold section's
5-word sequences (after normalization). Table/image placeholders are stripped from the
section; captions, headings and surrounding text are what get matched.

Questions with no gold chunk are `matched=False`: the runner leaves them out of retrieval
metrics and reports how many there were.

`--write` saves data/gold/<project-name>.json: all questions (unanswerable included) with
their gold chunk ids, the dataset file the runner reads.

Run from server/:
    python -m evaluation.open_ragbench.gold [--project-name evals] [--threshold 0.15]
        [--split dev|test] [--sample 10] [--seed 0] [--show ID ...] [--write]
"""
import os

# Must happen before importing src (see evaluation/open_ragbench/ingest.py)
os.environ.setdefault("LANGSMITH_PROJECT", "knowledgedock-eval")

import argparse
import json
import random
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from src.services.database import supabase

from evaluation.config import EVAL_PROJECT_NAME

DATA_DIR = Path(__file__).parent / "data"
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
CORPUS_DIR = DATA_DIR / "corpus"
RUNS_DIR = DATA_DIR / "ingest_runs"

DEFAULT_THRESHOLD = 0.15
SHINGLE_SIZE = 5
SWEEP = [0.05, 0.10, 0.15, 0.20, 0.30, 0.50]

_PLACEHOLDER = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HYPHEN_BREAK = re.compile(r"-\s+")
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class GoldMatch:
    gold_chunk_ids: set[str]
    best_coverage: float
    coverage: dict[str, float] = field(default_factory=dict)

    @property
    def matched(self) -> bool:
        return bool(self.gold_chunk_ids)


def normalize(text: str) -> list[str]:
    """Drop ![..](..) placeholders, re-join line-break hyphenation, lowercase, tokenize."""
    text = _PLACEHOLDER.sub(" ", text or "")
    text = _HYPHEN_BREAK.sub("", text)
    return _TOKEN.findall(text.lower())


def shingles(words: list[str], n: int = SHINGLE_SIZE) -> set[tuple]:
    """All n-word sequences; a text shorter than n words is one sequence."""
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def load_questions(answerable_only: bool = True, split: str | None = None) -> list[dict]:
    questions = [json.loads(line) for line in QUESTIONS_PATH.read_text().splitlines() if line.strip()]
    if answerable_only:
        questions = [q for q in questions if q.get("gold_section") is not None]
    if split:
        questions = [q for q in questions if q["split"] == split]
    return questions


@lru_cache(maxsize=None)
def _paper_sections(paper_id: str) -> list[dict]:
    return json.loads((CORPUS_DIR / f"{paper_id}.json").read_text())["sections"]


def load_section(paper_id: str, section_id: int) -> str:
    return _paper_sections(paper_id)[section_id]["text"]


@lru_cache(maxsize=None)
def _document_ids(project_name: str) -> dict[str, str]:
    run = json.loads((RUNS_DIR / f"{project_name}.json").read_text())
    return {paper_id: p["document_id"] for paper_id, p in run["papers"].items() if p.get("document_id")}


@lru_cache(maxsize=None)
def _paper_chunks(project_name: str, paper_id: str) -> tuple[dict, ...]:
    document_id = _document_ids(project_name)[paper_id]
    rows = (
        supabase.table("document_chunks")
        .select("id, chunk_index, page_number, original_content")
        .eq("document_id", document_id).order("chunk_index").execute()
    ).data
    out = []
    for r in rows:
        text = (r.get("original_content") or {}).get("text", "")
        out.append({
            "id": r["id"],
            "chunk_index": r["chunk_index"],
            "page_number": r["page_number"],
            "text": text,
            "shingles": shingles(normalize(text)),
        })
    return tuple(out)


def load_chunks(project_name: str, paper_ids) -> dict[str, tuple[dict, ...]]:
    """Chunks per paper (one select per paper, cached in memory)."""
    return {p: _paper_chunks(project_name, p) for p in set(paper_ids)}


def match_question(q: dict, chunks: tuple[dict, ...], threshold: float = DEFAULT_THRESHOLD) -> GoldMatch:
    section = shingles(normalize(load_section(q["gold_doc"], q["gold_section"])))
    if not section:
        return GoldMatch(set(), 0.0, {})
    coverage = {c["id"]: len(section & c["shingles"]) / len(section) for c in chunks}
    gold = {cid for cid, score in coverage.items() if score >= threshold}
    return GoldMatch(gold, max(coverage.values(), default=0.0), coverage)


def build_gold(project_name: str = EVAL_PROJECT_NAME, threshold: float = DEFAULT_THRESHOLD,
               split: str | None = None) -> dict[str, GoldMatch]:
    """question_id -> GoldMatch for every answerable question. Entry point for the runner."""
    questions = load_questions(split=split)
    chunks = load_chunks(project_name, (q["gold_doc"] for q in questions))
    return {q["id"]: match_question(q, chunks[q["gold_doc"]], threshold) for q in questions}


# ---------------------------------------------------------------- report

def _median(xs):
    return statistics.median(xs) if xs else 0.0


def _rethreshold(m: GoldMatch, t: float) -> int:
    return sum(score >= t for score in m.coverage.values())


def _print_breakdown(questions, matches, key):
    print(f"\nBy {key}:")
    print(f"  {key:<18} {'n':>4} {'matched':>8} {'unmatched':>10} {'med best cov':>13} {'med gold chunks':>16}")
    groups = defaultdict(list)
    for q in questions:
        groups[q[key]].append(matches[q["id"]])
    for name, ms in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        matched = [m for m in ms if m.matched]
        print(f"  {name:<18} {len(ms):>4} {len(matched):>8} {len(ms) - len(matched):>10} "
              f"{_median([m.best_coverage for m in ms]):>13.2f} "
              f"{_median([len(m.gold_chunk_ids) for m in matched]):>16}")


def _show(q, m: GoldMatch, chunks, width=300):
    print("\n" + "=" * 100)
    print(f"[{q['id']}] {q['source']} / {q['type']} / {q['split']}  paper={q['gold_doc']} section={q['gold_section']}")
    print(f"Q: {q['question']}")
    print(f"A: {q['reference_answer'][:width]}")
    section = load_section(q["gold_doc"], q["gold_section"])
    print(f"\n-- gold section ({len(normalize(section))} words) --\n{_PLACEHOLDER.sub('[*]', section)[:width]}")
    by_id = {c["id"]: c for c in chunks}
    ranked = sorted(m.coverage.items(), key=lambda kv: -kv[1])
    shown = [cid for cid, _ in ranked if cid in m.gold_chunk_ids] or [cid for cid, _ in ranked[:1]]
    label = "gold chunks" if m.gold_chunk_ids else "NO MATCH, best chunk"
    for cid in shown:
        c = by_id[cid]
        print(f"\n-- {label}: idx={c['chunk_index']} page={c['page_number']} cov={m.coverage[cid]:.2f} id={cid} --")
        print(c["text"][:width])


def write_gold_file(project_name: str = EVAL_PROJECT_NAME, threshold: float = DEFAULT_THRESHOLD) -> Path:
    """
    Write data/gold/<project-name>.json: every question (all splits, unanswerable included)
    with its gold chunks. This is the dataset file the runner reads.
    """
    run = json.loads((RUNS_DIR / f"{project_name}.json").read_text())
    questions = load_questions(answerable_only=False)
    answerable = [q for q in questions if q.get("gold_section") is not None]
    chunks = load_chunks(project_name, (q["gold_doc"] for q in answerable))
    doc_ids = _document_ids(project_name)

    out = []
    for q in questions:
        rec = {**q, "answerable": q.get("gold_section") is not None,
               "gold_document_id": doc_ids.get(q["gold_doc"])}
        if rec["answerable"]:
            m = match_question(q, chunks[q["gold_doc"]], threshold)
            by_id = {c["id"]: c for c in chunks[q["gold_doc"]]}
            gold = sorted(m.gold_chunk_ids, key=lambda cid: -m.coverage[cid])
            rec.update({
                "matched": m.matched,
                "best_coverage": round(m.best_coverage, 4),
                "gold_chunks": [{"id": cid, "chunk_index": by_id[cid]["chunk_index"],
                                 "page_number": by_id[cid]["page_number"],
                                 "coverage": round(m.coverage[cid], 4)} for cid in gold],
            })
        else:
            rec.update({"matched": None, "best_coverage": None, "gold_chunks": []})
        out.append(rec)

    path = DATA_DIR / "gold" / f"{project_name}.json"
    path.parent.mkdir(exist_ok=True)
    matched = sum(r["matched"] is True for r in out)
    path.write_text(json.dumps({
        "project_name": project_name,
        "project_id": run["project_id"],
        "threshold": threshold,
        "shingle_size": SHINGLE_SIZE,
        "counts": {"questions": len(out), "answerable": len(answerable),
                   "matched": matched, "unmatched": len(answerable) - matched,
                   "unanswerable": len(out) - len(answerable)},
        "questions": out,
    }, indent=2))
    return path


def report(project_name, threshold, split, sample, seed, show_ids):
    questions = load_questions(split=split)
    chunks = load_chunks(project_name, (q["gold_doc"] for q in questions))
    matches = {q["id"]: match_question(q, chunks[q["gold_doc"]], threshold) for q in questions}
    by_id = {q["id"]: q for q in questions}

    if show_ids:
        for qid in show_ids:
            if qid not in by_id:
                print(f"\n{qid}: not an answerable question in this split")
                continue
            _show(by_id[qid], matches[qid], chunks[by_id[qid]["gold_doc"]])
        return

    n = len(questions)
    unmatched = [q for q in questions if not matches[q["id"]].matched]
    print(f"Project: {project_name}  threshold: {threshold}  split: {split or 'all'}")
    print(f"Answerable questions: {n}  matched: {n - len(unmatched)}  "
          f"unmatched (left out of retrieval metrics): {len(unmatched)} ({len(unmatched) / n:.1%})")

    _print_breakdown(questions, matches, "source")
    _print_breakdown(questions, matches, "type")

    print(f"\nUnmatched ({len(unmatched)}):")
    for q in unmatched:
        print(f"  {q['id']}  {q['source']:<17} best={matches[q['id']].best_coverage:.2f}  {q['question'][:90]}")

    print("\nThreshold sweep:")
    print(f"  {'threshold':>9} {'matched':>8} {'mean gold chunks':>17}")
    for t in SWEEP:
        counts = [_rethreshold(matches[q["id"]], t) for q in questions]
        hit = [c for c in counts if c]
        print(f"  {t:>9.2f} {len(hit):>8} {statistics.mean(hit) if hit else 0:>17.2f}")

    if sample:
        rng = random.Random(seed)
        pool = questions[:]
        rng.shuffle(pool)
        picked, seen = [], set()
        for q in pool:  # one per source first, then fill
            if q["source"] not in seen:
                picked.append(q)
                seen.add(q["source"])
        picked = picked[:sample]
        picked += [q for q in pool if q not in picked][:sample - len(picked)]
        print(f"\nHand-check sample ({len(picked)}, seed {seed}):")
        for q in picked:
            _show(q, matches[q["id"]], chunks[q["gold_doc"]])


def main():
    parser = argparse.ArgumentParser(description="Match Open RAGBench gold sections to indexed chunks.")
    parser.add_argument("--project-name", default=EVAL_PROJECT_NAME)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--split", choices=["dev", "test"])
    parser.add_argument("--sample", type=int, default=0, help="Print N random questions for hand-checking")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--show", nargs="+", metavar="ID", help="Print the match view for these question ids")
    parser.add_argument("--write", action="store_true",
                        help="Also write data/gold/<project-name>.json (all questions with their gold chunks)")
    args = parser.parse_args()
    report(args.project_name, args.threshold, args.split, args.sample, args.seed, args.show)
    if args.write:
        print(f"\nWrote {write_gold_file(args.project_name, args.threshold)}")


if __name__ == "__main__":
    main()
