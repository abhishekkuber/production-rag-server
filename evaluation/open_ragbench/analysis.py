"""
One-off investigations on saved eval runs (no LLM calls, no API cost).

Run from server/:
    python -m evaluation.open_ragbench.analysis prompt-size --run no-rerank
    python -m evaluation.open_ragbench.analysis label-export --run no-rerank [--n 20] [--seed 0]
    python -m evaluation.open_ragbench.analysis label-sources --run no-rerank
    python -m evaluation.open_ragbench.analysis label-agreement --run no-rerank

prompt-size (A1)
    Explains the generator's input tokens per question. For each generated question it reads
    the final chunks from the local Supabase, counts images / tables / text, estimates the text
    tokens with tiktoken and the image tokens with OpenAI's image formula for gpt-4o-mini, and
    compares the sum with the observed input tokens. The fixed prompt overhead (instructions,
    headers, message framing) is calibrated as the median gap on questions without images.

label-export / label-agreement (A2)
    Checks the Ragas metrics against hand labels. label-export writes a stratified sample of
    answered questions to data/labels/<run>.json with empty label fields and WITHOUT the Ragas
    scores (so they can't anchor the labels). After the labels are filled in and reviewed,
    label-agreement joins them with the Ragas scores and reports correlation, agreement at a
    0.5 threshold, the disagreements, and whether AnswerCorrectness tracks answer length.
"""
import os

# Must happen before importing src (see evaluation/open_ragbench/ingest.py)
os.environ.setdefault("LANGSMITH_PROJECT", "knowledgedock-eval")

import argparse
import base64
import io
import json
import math
import random
import statistics
from pathlib import Path

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "data" / "results"
LABELS_DIR = HERE / "data" / "labels"

# gpt-4o-mini image tokens (OpenAI pricing docs): low detail = base; high detail = base + per tile.
# gpt-4o-mini bills images at ~33x the tokens of gpt-4o, so the dollar cost per image is similar.
IMG_BASE_TOKENS = 2833
IMG_TILE_TOKENS = 5667
GPT4O_MINI_INPUT_USD_PER_M = 0.15


def load_run(name: str) -> dict:
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"{path} missing")
    return json.loads(path.read_text())


# ============================================================================ A1 prompt size

def image_tokens_high(width: int, height: int) -> int:
    """gpt-4o-mini tokens for one image at high detail (OpenAI's tiling formula)."""
    if max(width, height) > 2048:  # fit within 2048 x 2048
        s = 2048 / max(width, height)
        width, height = width * s, height * s
    if min(width, height) > 768:   # shortest side down to 768
        s = 768 / min(width, height)
        width, height = width * s, height * s
    tiles = math.ceil(width / 512) * math.ceil(height / 512)
    return IMG_BASE_TOKENS + IMG_TILE_TOKENS * tiles


def _image_size(b64: str) -> tuple[int, int] | None:
    from PIL import Image
    if b64.startswith("data:image"):
        b64 = b64.split(",", 1)[1]
    try:
        with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
            return im.size
    except Exception:
        return None


def _fetch_chunks(ids: list[str]) -> dict[str, dict]:
    from src.services.database import supabase
    if not ids:
        return {}
    rows = supabase.table("document_chunks").select("id, original_content").in_("id", ids).execute().data
    return {r["id"]: r for r in rows}


def prompt_size(run_name: str, top: int):
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")
    run = load_run(run_name)
    recs = [r for r in run["questions"] if r["tokens"]["input"]]
    print(f"Run '{run_name}': {len(recs)} questions with a generation call")

    rows = []
    for r in recs:
        chunks = _fetch_chunks(r["final_chunk_ids"])
        images = []
        for cid in r["final_chunk_ids"]:
            images += (chunks.get(cid, {}).get("original_content") or {}).get("images") or []
        sizes = [_image_size(b) for b in images]
        text_tok = len(enc.encode("\n".join(r["contexts"]))) + len(enc.encode(r["question"]))
        rows.append({
            "id": r["id"], "source": r["source"], "observed": r["tokens"]["input"],
            "text_tokens": text_tok, "n_images": len(images),
            "sizes": sizes, "image_tokens": sum(image_tokens_high(*s) for s in sizes if s),
            "undecodable": sum(1 for s in sizes if s is None),
        })

    no_img = [x for x in rows if not x["n_images"]]
    overhead = statistics.median(x["observed"] - x["text_tokens"] for x in no_img) if no_img else 0
    for x in rows:
        x["estimated"] = x["text_tokens"] + overhead + x["image_tokens"]

    total = sum(x["observed"] for x in rows)
    img_rows = [x for x in rows if x["n_images"]]
    est_img = sum(x["image_tokens"] for x in rows)
    print(f"\nPrompt overhead (median gap on {len(no_img)} image-free questions): {overhead:.0f} tokens")
    print(f"Observed input tokens: total {total:,}, median {statistics.median(x['observed'] for x in rows):,.0f}, "
          f"mean {total / len(rows):,.0f}")
    print(f"Questions with images in the final context: {len(img_rows)} of {len(rows)}; "
          f"images per such question: median {statistics.median(x['n_images'] for x in img_rows) if img_rows else 0}, "
          f"max {max((x['n_images'] for x in rows), default=0)}")
    print(f"Tokens from those questions: {sum(x['observed'] for x in img_rows):,} "
          f"({sum(x['observed'] for x in img_rows) / total:.0%} of all input tokens)")
    print(f"Estimated image tokens: {est_img:,} ({est_img / total:.0%} of all input tokens)")
    print(f"Input cost at ${GPT4O_MINI_INPUT_USD_PER_M}/M: ${total * GPT4O_MINI_INPUT_USD_PER_M / 1e6:.3f} for the run, "
          f"of which images about ${est_img * GPT4O_MINI_INPUT_USD_PER_M / 1e6:.3f}")
    errs = [abs(x["estimated"] - x["observed"]) / x["observed"] for x in img_rows]
    if errs:
        print(f"Estimate vs observed on image questions: median error {statistics.median(errs):.1%}, "
              f"max {max(errs):.1%}")
    bad = sum(x["undecodable"] for x in rows)
    if bad:
        print(f"WARNING: {bad} images could not be decoded (not counted in the estimate)")

    print(f"\nTop {top} questions by observed input tokens:")
    print(f"  {'id':<14} {'source':<17} {'observed':>9} {'text':>7} {'images':>6} {'img tok':>9} {'estimate':>9}  sizes")
    for x in sorted(rows, key=lambda x: -x["observed"])[:top]:
        sizes = ", ".join(f"{s[0]}x{s[1]}" if s else "?" for s in x["sizes"][:4])
        if len(x["sizes"]) > 4:
            sizes += f", ... (+{len(x['sizes']) - 4})"
        print(f"  {x['id'][:14]:<14} {x['source']:<17} {x['observed']:>9,} {x['text_tokens']:>7,} "
              f"{x['n_images']:>6} {x['image_tokens']:>9,} {x['estimated']:>9,.0f}  {sizes}")


# ============================================================================ A2 labels

LABEL_FIELDS = {"correct": None, "faithful": None, "relevant": None, "note": ""}
LABEL_HELP = {
    "correct": "0 | 0.5 | 1  - does the answer agree with the reference answer?",
    "faithful": "yes | partly | no  - is every claim supported by the contexts?",
    "relevant": "yes | no  - does the answer address the question?",
}


def label_export(run_name: str, n: int, seed: int, overwrite: bool):
    run = load_run(run_name)
    path = LABELS_DIR / f"{run_name}.json"
    if path.exists() and not overwrite:
        raise SystemExit(f"{path} exists (it may hold labels). Pass --overwrite to replace it.")
    recs = [r for r in run["questions"] if r["answerable"] and r.get("ragas")
            and r["ragas"].get("answer_correctness") is not None]
    rng = random.Random(seed)
    refused = [r for r in recs if "don't have enough information" in (r["answer"] or "")]
    picked = rng.sample(refused, min(2, len(refused)))
    rest = sorted((r for r in recs if r not in picked), key=lambda r: r["ragas"]["answer_correctness"])
    per_q, q = (n - len(picked)) // 4, len(rest) // 4
    for i in range(4):  # stratify by AnswerCorrectness quartile; spread sources within a quartile
        bucket = rest[i * q:(i + 1) * q] if i < 3 else rest[3 * q:]
        rng.shuffle(bucket)
        bucket.sort(key=lambda r: sum(1 for p in picked if p["source"] == r["source"]))
        picked += bucket[:per_q]
    picked += [r for r in rest if r not in picked][:n - len(picked)]
    rng.shuffle(picked)

    items = [{
        "id": r["id"], "source": r["source"], "type": r["type"],
        "question": r["question"], "reference_answer": r["reference_answer"], "answer": r["answer"],
        "contexts": r["contexts"],
        "labels": dict(LABEL_FIELDS), "draft_by": None, "reviewed": False,
    } for r in picked]
    LABELS_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps({"run": run_name, "seed": seed, "label_help": LABEL_HELP,
                                "items": items}, indent=2))
    print(f"Wrote {len(items)} items to {path} (Ragas scores left out on purpose)")


def label_agreement(run_name: str):
    from scipy.stats import spearmanr
    run = load_run(run_name)
    data = json.loads((LABELS_DIR / f"{run_name}.json").read_text())
    by_id = {r["id"]: r for r in run["questions"]}
    items = [it for it in data["items"] if it["labels"]["correct"] is not None]
    unreviewed = sum(1 for it in items if not it["reviewed"])
    print(f"{len(items)} labelled items ({unreviewed} not reviewed yet)")

    to_num = {"yes": 1.0, "partly": 0.5, "no": 0.0}
    pairs = {  # ragas metric -> (label field, label value as number)
        "answer_correctness": ("correct", lambda v: float(v)),
        "faithfulness": ("faithful", lambda v: to_num[v]),
        "answer_relevancy": ("relevant", lambda v: to_num[v]),
    }
    refusal = lambda it: "don't have enough information" in it["answer"]
    for metric, (field, conv) in pairs.items():
        for label, subset in (("all", items), ("non-refused", [it for it in items if not refusal(it)])):
            xs = [(by_id[it["id"]]["ragas"][metric], conv(it["labels"][field])) for it in subset
                  if by_id[it["id"]]["ragas"].get(metric) is not None and it["labels"][field] is not None]
            if len(xs) < 3:
                continue
            rho = spearmanr([a for a, _ in xs], [b for _, b in xs]).statistic
            agree = sum((a >= 0.5) == (b >= 0.5) for a, b in xs) / len(xs)
            print(f"  {metric:<19} {label:<12} n={len(xs):>2}  spearman={rho:+.2f}  agreement@0.5={agree:.0%}")

    print("\nDisagreements (Ragas on the other side of 0.5 from the label):")
    for it in items:
        rg = by_id[it["id"]]["ragas"]
        for metric, (field, conv) in pairs.items():
            v = it["labels"][field]
            if rg.get(metric) is None or v is None:
                continue
            if (rg[metric] >= 0.5) != (conv(v) >= 0.5):
                print(f"  {it['id'][:14]:<14} {metric:<19} ragas={rg[metric]:.2f} label={v}  {it['labels']['note']}")

    print("\nVerbosity: does AnswerCorrectness track answer length?")
    xs = [(by_id[it["id"]]["ragas"]["answer_correctness"], len(it["answer"].split()),
           len(it["answer"].split()) / max(1, len(it["reference_answer"].split())))
          for it in items if not refusal(it)]
    if len(xs) >= 3:
        print(f"  spearman(correctness, answer words) = {spearmanr([a for a, _, _ in xs], [b for _, b, _ in xs]).statistic:+.2f}")
        print(f"  spearman(correctness, answer/reference length) = {spearmanr([a for a, _, _ in xs], [c for _, _, c in xs]).statistic:+.2f}")
    right = [by_id[it["id"]]["ragas"]["answer_correctness"] for it in items if it["labels"]["correct"] == 1]
    if right:
        print(f"  AnswerCorrectness on answers labelled correct=1: mean {statistics.mean(right):.2f}, "
              f"min {min(right):.2f} (n={len(right)})")


DATA_DIR = HERE / "data"


def label_sources(run_name: str):
    """
    Add a `source_info` block to every label item (labels untouched) and write a review sheet
    data/labels/<run>.review.md: per item the paper (title, local PDF, arXiv link), the gold
    section's text from the dataset, the pages of the gold chunks, which context holds the gold
    chunk, the answer and the current labels. Files only, no API calls.
    """
    path = LABELS_DIR / f"{run_name}.json"
    data = json.loads(path.read_text())
    gold = {q["id"]: q for q in json.loads((DATA_DIR / "gold" / "evals.json").read_text())["questions"]}
    urls = json.loads((DATA_DIR / "raw" / "pdf_urls.json").read_text())
    run = {r["id"]: r for r in load_run(run_name)["questions"]}
    papers = {}

    def paper(pid):
        if pid not in papers:
            f = DATA_DIR / "corpus" / f"{pid}.json"
            papers[pid] = json.loads(f.read_text()) if f.exists() else None
        return papers[pid]

    lines = [f"# Hand-label review sheet: `{run_name}`", "",
             f"Edit the labels in `{path.name}` (this sheet is regenerated by "
             f"`analysis.py label-sources --run {run_name}`).", "",
             "Label guide: " + "; ".join(f"**{k}** {v}" for k, v in data["label_help"].items()), ""]
    for n, it in enumerate(data["items"]):
        g, rec = gold[it["id"]], run[it["id"]]
        p = paper(g["gold_doc"])
        section = next((s for s in (p or {}).get("sections", []) if s["section_id"] == g["gold_section"]), None)
        gold_ids = {c["id"] for c in g["gold_chunks"]}
        ctx_with_gold = [i for i, cid in enumerate(rec["final_chunk_ids"], 1) if cid in gold_ids]
        it["source_info"] = {
            "paper_id": g["gold_doc"],
            "paper_title": (p or {}).get("title"),
            "pdf": f"evaluation/open_ragbench/data/pdfs/{g['gold_doc']}.pdf",
            "arxiv": urls.get(g["gold_doc"], f"https://arxiv.org/pdf/{g['gold_doc']}").replace("/pdf/", "/abs/"),
            "gold_section_id": g["gold_section"],
            "gold_pages": sorted({c["page_number"] for c in g["gold_chunks"] if c.get("page_number")}),
            "gold_in_context": ctx_with_gold,   # 1-based chunk positions in the generator's context
        }
        s = it["source_info"]
        lines += [
            "---", "", f"## [{n}] {it['source']}/{it['type']} · `{it['id'][:8]}`", "",
            f"**Paper:** {s['paper_title'] or '(title not in corpus)'}  ",
            f"**Local PDF:** `{s['pdf']}` · **arXiv:** {s['arxiv']}  ",
            f"**Gold section:** {s['gold_section_id']} · **pages:** {', '.join(map(str, s['gold_pages'])) or '?'} · "
            f"**gold chunk in context:** {', '.join(f'chunk {i}' for i in ctx_with_gold) or 'NO (retrieval miss)'}", "",
            f"**Question:** {it['question']}", "",
            f"**Reference answer:** {it['reference_answer']}", "",
            f"**System answer:**", "", "> " + it["answer"].replace("\n", "\n> "), "",
            f"**Current labels** ({'reviewed' if it['reviewed'] else 'draft by ' + str(it['draft_by'])}): "
            + ", ".join(f"{k}={v}" for k, v in it["labels"].items() if k != "note"), "",
            f"**Note:** {it['labels'].get('note') or '-'}", "",
            "<details><summary>Gold section text (from the dataset)</summary>", "",
            (section["text"] if section else "(section not found in corpus)"), "", "</details>", "",
        ]
    path.write_text(json.dumps(data, indent=2))
    sheet = LABELS_DIR / f"{run_name}.review.md"
    sheet.write_text("\n".join(lines))
    print(f"Added `source_info` to {len(data['items'])} items in {path}\nWrote {sheet}")


# ============================================================================ CLI

def main():
    parser = argparse.ArgumentParser(description="One-off investigations on saved eval runs.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prompt-size", help="A1: where the generator's input tokens come from")
    p.add_argument("--run", required=True)
    p.add_argument("--top", type=int, default=10)
    p = sub.add_parser("label-export", help="A2: write a labelling sample")
    p.add_argument("--run", required=True)
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--overwrite", action="store_true")
    p = sub.add_parser("label-sources", help="A2: add paper / section / page info and write a review sheet")
    p.add_argument("--run", required=True)
    p = sub.add_parser("label-agreement", help="A2: Ragas vs hand labels")
    p.add_argument("--run", required=True)
    args = parser.parse_args()

    if args.cmd == "prompt-size":
        prompt_size(args.run, args.top)
    elif args.cmd == "label-sources":
        label_sources(args.run)
    elif args.cmd == "label-export":
        label_export(args.run, args.n, args.seed, args.overwrite)
    else:
        label_agreement(args.run)


if __name__ == "__main__":
    main()
