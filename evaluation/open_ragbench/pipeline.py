"""
Open RAGBench eval pipeline: run questions through the app's core RAG path with the settings
from an experiment config, compute retrieval metrics, save and compare runs.

Purpose
=======
Pick the best query-time hyperparameters. Each experiment is one YAML file in configs/.
A run sends every question of the config's split through the app's own retrieval (and
optionally generation) code with those settings, scores retrieval against the gold chunks,
and saves a results file. Runs are then compared side by side.

When generation is on, answers are also scored with Ragas (Faithfulness, AnswerRelevancy,
AnswerCorrectness) in a second pass after all questions are answered.

Prerequisites
=============
- Local Supabase running (./start_db.sh) with the `evals` project indexed (ingest.py).
- data/gold/<project>.json written by `python -m evaluation.open_ragbench.gold --write`.

How to run (from server/)
=========================
1. Run an experiment (results -> data/results/<config name>.json):
       python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/baseline.yaml

2. Compare saved runs (one row per run, sorted by MRR, with deltas vs --vs):
       python -m evaluation.open_ragbench.pipeline --compare baseline cps20 [--by modality] [--vs baseline]
       python -m evaluation.open_ragbench.pipeline --compare all --by modality
   Paired comparison of two runs (wins / losses, McNemar p, bootstrap 95% CI, tie verdict):
       python -m evaluation.open_ragbench.pipeline --paired baseline cps20
   Recompute the metrics of saved runs after a metric change (no API calls):
       python -m evaluation.open_ragbench.pipeline --rescore no-rerank baseline

3. Inspect one question in detail (ranked chunks with gold marked, answer, tokens, timings),
   optionally with an experiment's settings:
       python -m evaluation.open_ragbench.pipeline --question-id <ID> [--config <yaml>] [--retrieval-only]

Experiment config (configs/<name>.yaml; the file name is the run name)
=====================================================================
    description: hybrid search, wider candidate list   # optional, free text
    split: dev                # dev | test. Tune on dev only; run test once per final config.
    retrieval_only: false     # true = skip generation and Ragas: retrieval metrics only,
                              # cheaper and faster. false = also generate and score answers.
    guardrail: false          # true = run the app's input guardrail first; a blocked question
                              # gets the app's refusal text and no retrieval.
    settings:                 # overrides on top of the project's DB settings; omit = DB value
      rag_strategy: hybrid    # basic | hybrid | multi-query-vector | multi-query-hybrid
      chunks_per_search: 20   # chunks returned by each search = length of the ranked list
      final_context_size: 5   # chunks kept after rerank and passed to the generator
      similarity_threshold: 0.3   # minimum cosine similarity in vector search
      number_of_queries: 5    # query variations for the multi-query strategies
      reranking_enabled: true # Cohere rerank on/off
      reranking_model: rerank-english-v3.0
      vector_weight: 0.7      # RRF weights for hybrid search
      keyword_weight: 0.3
Only these query-time settings are accepted; any other key (in `settings` or at the top level)
raises ValueError. Ingestion-time settings (embedding_model, chunking) are fixed in src and
can't change per run. The generator model is always the app default (open_ai_models["chat_llm"]).

Command-line options
====================
--config PATH         experiment config (mode 1, or settings for mode 3)
--compare NAME ...    mode 2: comparison table of saved runs ('all' = every results file)
--by GROUP            --compare: also print modality | source | type rows
--vs NAME             --compare: reference run for the delta rows (default: baseline)
--paired A B          paired comparison of two saved runs (B - A)
--rescore NAME ...    recompute derived fields and metrics of saved runs from their records
--question-id ID      mode 3: one question in detail
--retrieval-only      mode 3 only: skip generation
--workers N           questions processed in parallel (default 4)
--limit N             only the first N questions (quick trial; the run is named <name>-limitN)
--overwrite           replace an existing results file of the same name (refused otherwise)
--reuse-retrieval NAME  take each question's ranked list from saved run NAME instead of searching
                      and reranking again. The ranking settings (RANKING_KEYS) must match NAME's;
                      final_context_size may differ. Questions missing from NAME (e.g. the
                      unanswerable ones, which retrieval-only runs skip) run live. Saves Cohere
                      calls and guarantees the generation runs see exactly the shortlisted retrieval.
--project-name NAME   eval project (default: evals); selects gold/<name>.json

What is calculated
==================
Per question: the search order (before rerank), the ranked list (after rerank, before the cap),
the final context (first final_context_size chunks), the rerank status
(disabled | ok | empty | failed), and when generating: the answer, the contexts given to the
generator (texts + tables), and token counts. Timings for search, rerank, generation, total.

Retrieval metrics, over answerable questions whose gold section matched at least one chunk
(the unmatched ones are left out and counted; unanswerable ones have no gold):
    Hit@k (k = 1, 3, 5, 10)  share of questions with a gold chunk in the top k of the ranked list
    MRR                      mean of 1/rank of the first gold chunk (0 if not in the ranked list)
    Context hit              share with a gold chunk in the final context (what the generator sees)
    Pool hit                 share with a gold chunk among the search candidates BEFORE rerank.
                             Splits misses into search misses (not in the pool) and rerank misses
                             (in the pool, not in the final context).
    Paper Hit@k, Paper MRR   the same as Hit@k / MRR, where any chunk of the gold paper counts
Each is reported overall, by modality (text-only = text, text-table; with-image = text-image,
text-table-image), by question source and by type (extractive, abstractive).
Run stats: errors, rerank failures / retries, empty retrievals, guardrail blocks, p50/p95
latency per stage, generator tokens.

Refusal metrics (when generating), overall and by group:
    refusal_accuracy         share of unanswerable questions answered with the app's refusal
    false_refusal_rate       share of answerable questions refused; the false refusals are split
                             into gold in context (a generator problem), gold not in context (a
                             retrieval problem) and unmatched
A refusal is the app's refusal sentence (REFUSAL_MARKERS) or the no-context answer.

Cost per query (cost, per record cost_usd), in USD at PRICE_PER_M:
    generation               generator tokens from the API
    retrieval_llm            the multi-query variation call's tokens from the API
    embeddings_est           question embeddings: question tokens x number of queries (estimate)
    rerank_list              Cohere LIST price per search (the trial key is free)
Reported as p50 / mean / p95 / max per query and run totals. The Ragas judge's cost is an
eval cost, not a per-query cost: it is in ragas.tokens / ragas.cost_usd.

Answer-quality metrics (Ragas 0.4.3 collections; only when generating). Scored over answerable
questions that got an answer (no error, not guardrail-blocked, not a refusal); the 6 unmatched
questions ARE included because these metrics don't need gold chunks. Refusals are left out
because Ragas scores them inconsistently (faithfulness 0 or 1 for the same sentence) and they
are measured by the refusal metrics instead; so a config can't look better by refusing more.
Unanswerable questions have no reference answer, so they are generated and saved but not
scored. All are 0-1, higher is better:
    faithfulness        share of the answer's claims supported by the contexts given to the
                        generator (texts + tables; images are not passed to the judge).
                        Not scored when retrieval returned nothing (no contexts to check).
    answer_relevancy    how directly the answer addresses the question: the judge writes
                        questions from the answer, compared to the real one by embedding
                        similarity. Evasive or non-committal answers score low.
    answer_correctness  agreement with the reference answer: 0.75 x factual overlap (claim
                        F1, judged by the LLM) + 0.25 x embedding similarity.
Reported as means overall and by group, with the count scored per metric.
Checked against hand labels (analysis.py label-agreement): AnswerCorrectness compresses correct
answers into ~0.3-0.6, so read it as a relative signal (paired deltas), not an absolute score.
Judge: RAGAS_JUDGE_MODEL, embeddings: RAGAS_EMBEDDING_MODEL (constants below). A failed metric
call is stored per question under ragas_errors and counted in stats.ragas_failed; it is left out
of the mean, not counted as 0. Ragas time is in wall_seconds but not in the latency numbers.

Cohere rate limit
=================
The app silently falls back to search order when Cohere fails. Here every rerank call is
spaced to stay under RERANK_CALLS_PER_MINUTE (10, the trial-key limit; raise it with a
production key), a 429 response is retried up to RERANK_MAX_RETRIES times with backoff, and
any failure left after that is counted and flagged. With the trial key, a rerank-on run takes
about 6 s per question (~12 min for the 112 dev questions); rerank-off runs are not throttled.
Time spent waiting is recorded as timings.rerank_wait and kept out of the latency numbers.

Caveat: the ranked list has at most chunks_per_search chunks, so Hit@k for k > chunks_per_search
can't improve beyond Hit@chunks_per_search. Compare Hit@k across runs only for k <= the smallest
chunks_per_search; Context hit is always comparable.

Results file (data/results/<name>.json)
=======================================
name, created_at, git commit, config path and full config, merged settings, counts, metrics
(overall / by_source / by_type), answer_metrics (same shape; null for retrieval-only runs),
ragas (judge and embedding models, seconds), stats, and one record per question (gold ids,
ranked ids, ranks, answer, contexts, ragas scores and errors, tokens, timings, errors).

src/ is never modified
======================
This file only imports and calls app code, so the app keeps its original behaviour:
  src/rag/retrieval/db.py              get_project_settings, get_project_documents
  src/rag/retrieval/search.py          vector_search, hybrid_search,
                                       multi_query_vector_search, multi_query_hybrid_search
  src/rag/retrieval/reranker.py        _chunk_to_document_text (same rerank payload)
  src/services/cohere_reranker.py      cohere_reranker (same Cohere client)
  src/rag/retrieval/context_builder.py separate_content_types
  src/rag/retrieval/utils.py           prepare_prompt_and_invoke_llm (app prompt and model)
  src/agents/simple_agent/agent.py     check_input_guardrails
  src/config/index.py                  app_config (OpenAI key for the Ragas judge)
retrieve_ranked() repeats the steps of src/rag/retrieval/index.py:retrieve_context_and_build_prompt
so it can also return the full ranked list and the rerank status; with no overrides it returns
the same final chunks as the app. It covers the core path only (question -> search -> rerank ->
cap -> one generation call), not the agent's query and answer rewrites.
"""
import os

# Must happen before importing src (see evaluation/open_ragbench/ingest.py)
os.environ.setdefault("LANGSMITH_PROJECT", "knowledgedock-eval")
# Ragas sends usage analytics by default; turn that off
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

import argparse
import asyncio
import json
import math
import subprocess
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from langchain_core.callbacks import get_usage_metadata_callback

from src.agents.simple_agent.agent import check_input_guardrails
from src.config.index import app_config
from src.config.logging import set_project_id
from src.rag.retrieval.context_builder import separate_content_types
from src.rag.retrieval.db import get_project_settings, get_project_documents
from src.rag.retrieval.reranker import _chunk_to_document_text
from src.rag.retrieval.search import (
    vector_search, hybrid_search, multi_query_vector_search, multi_query_hybrid_search,
)
from src.rag.retrieval.utils import prepare_prompt_and_invoke_llm
from src.services.cohere_reranker import cohere_reranker
from src.services.llm import open_ai_models

from evaluation.config import EVAL_PROJECT_NAME

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
GOLD_DIR = DATA_DIR / "gold"
RESULTS_DIR = DATA_DIR / "results"
CONFIGS_DIR = HERE / "configs"

# Same mapping as src/rag/retrieval/index.py
SEARCH_STRATEGIES = {
    "basic": vector_search,
    "hybrid": hybrid_search,
    "multi-query-vector": multi_query_vector_search,
    "multi-query-hybrid": multi_query_hybrid_search,
}

TUNABLE_KEYS = {
    "rag_strategy", "chunks_per_search", "final_context_size", "similarity_threshold",
    "number_of_queries", "reranking_enabled", "reranking_model", "vector_weight", "keyword_weight",
}
CONFIG_KEYS = {"description", "split", "retrieval_only", "guardrail", "settings"}

# Same texts as the app (simple agent's rag_search tool and guardrail_node)
NO_CONTEXT_ANSWER = "No relevant information found in the project documents for this query."
GUARDRAIL_ANSWER = "I cannot process this request. {reason}"

HIT_KS = (1, 3, 5, 10)

# Cohere rate limit. The trial key allows 10 calls/minute; raise this with a production key.
# All rerank calls (across worker threads, retries included) are spaced to stay under it.
RERANK_CALLS_PER_MINUTE = 10
RERANK_MAX_RETRIES = 5         # retries after a 429 (rate limited) response
RERANK_RETRY_BACKOFF = 15.0    # seconds; wait = backoff * attempt

# Ragas answer-quality scoring (only when generating)
RAGAS_JUDGE_MODEL = "gpt-4o-mini"                 # same model as the app's generator
RAGAS_EMBEDDING_MODEL = "text-embedding-3-small"  # for answer_relevancy / answer_correctness
RAGAS_JUDGE_MAX_TOKENS = 8192   # Ragas default 1024 truncates faithfulness on long answers
RAGAS_CONCURRENCY = 16                            # questions scored at the same time
RAGAS_METRICS = ("faithfulness", "answer_relevancy", "answer_correctness")

# Prices in USD (as of 2026-11; check before quoting). Per 1M tokens: (input, output).
PRICE_PER_M = {
    "gpt-4o-mini": (0.15, 0.60),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-3-small": (0.02, 0.0),
}
GENERATOR_MODEL = open_ai_models["chat_llm"].model_name  # also writes the multi-query variations
RERANK_USD_PER_SEARCH = 0.002   # Cohere LIST price ($2 per 1k searches); the trial key is free
RERANK_DOCS_PER_SEARCH = 100    # Cohere bills one search per query + up to 100 documents
COST_PARTS = ("generation", "retrieval_llm", "embeddings_est", "rerank_list")

# The app's refusal sentence (system prompt in src/rag/retrieval/utils.py), lower-cased
REFUSAL_MARKERS = ("i don't have enough information in the provided context",)

# Question source -> modality (B3: text-only vs image questions)
MODALITY = {"text": "text-only", "text-table": "text-only", "text-image": "with-image", "text-table-image": "with-image"}

TIE_POINTS = 0.03   # differences under 3 points (on a 0-1 scale) count as a tie (~1 question = 1 point)
BOOTSTRAP_SAMPLES = 10_000


class _RateLimiter:
    """Thread-safe spacing of calls: at most `per_minute` calls per 60 seconds."""

    def __init__(self, per_minute: int):
        self.interval = 60.0 / per_minute
        self.next_at = 0.0
        self.lock = threading.Lock()

    def wait(self) -> float:
        """Block until a call is allowed; return the seconds waited."""
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at)
            self.next_at = start + self.interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)
        return delay


_rerank_limiter = _RateLimiter(RERANK_CALLS_PER_MINUTE)


# ============================================================================ config

def load_config(path: str | Path) -> dict:
    """Read and validate an experiment YAML. Adds `name` (the file stem) and `path`."""
    path = Path(path)
    cfg = yaml.safe_load(path.read_text()) or {}
    bad = set(cfg) - CONFIG_KEYS
    if bad:
        raise ValueError(f"{path.name}: unknown top-level keys {sorted(bad)}. Allowed: {sorted(CONFIG_KEYS)}")
    if cfg.get("split") not in ("dev", "test"):
        raise ValueError(f"{path.name}: `split` must be dev or test")
    cfg.setdefault("retrieval_only", False)
    cfg.setdefault("guardrail", False)
    cfg["settings"] = cfg.get("settings") or {}
    bad = set(cfg["settings"]) - TUNABLE_KEYS
    if bad:
        raise ValueError(f"{path.name}: not tunable per run {sorted(bad)}. Allowed: {sorted(TUNABLE_KEYS)}")
    cfg["name"] = path.stem
    cfg["path"] = str(path)
    return cfg


def merge_settings(project_id: str, override: dict | None) -> dict:
    """Project DB settings with the override on top. Only TUNABLE_KEYS may be overridden."""
    override = override or {}
    bad = set(override) - TUNABLE_KEYS
    if bad:
        raise ValueError(f"Not tunable per run: {sorted(bad)}. Allowed: {sorted(TUNABLE_KEYS)}")
    settings = {**get_project_settings(project_id), **override}
    if settings["rag_strategy"] not in SEARCH_STRATEGIES:
        raise ValueError(f"Unknown rag_strategy {settings['rag_strategy']!r}. "
                         f"Allowed: {sorted(SEARCH_STRATEGIES)}")
    return settings


# ============================================================================ adapter

@dataclass
class RetrievalResult:
    settings: dict
    search_ids: list[str]
    ranked: list[dict]
    final: list[dict]
    texts: list[str]
    images: list[str]
    tables: list[str]
    citations: list[dict]
    rerank_status: str
    rerank_error: str | None = None
    rerank_retries: int = 0
    timings: dict = field(default_factory=dict)


def _is_rate_limited(e: Exception) -> bool:
    return getattr(e, "status_code", None) == 429 or "status_code: 429" in str(e)


def _rerank(query: str, chunks: list[dict], model: str) -> tuple[list[dict], str, str | None, int, float]:
    """
    Same Cohere call, index checks and fallback as src cohere_rerank_chunks, plus:
    rate limiting, retries on 429, and the branch taken.
    Returns (chunks, status, error, retries, seconds spent waiting).
    """
    documents = [_chunk_to_document_text(c) for c in chunks]
    waited, retries = 0.0, 0
    while True:
        waited += _rerank_limiter.wait()
        try:
            response = cohere_reranker.rerank(
                model=model, query=query, documents=documents, top_n=len(chunks),
            )
            break
        except Exception as e:
            if _is_rate_limited(e) and retries < RERANK_MAX_RETRIES:
                retries += 1
                pause = RERANK_RETRY_BACKOFF * retries
                time.sleep(pause)
                waited += pause
                continue
            return chunks, "failed", str(e), retries, waited

    ranked = []
    for result in response.results:
        idx = getattr(result, "index", None)
        if idx is None or idx < 0 or idx >= len(chunks):
            continue
        ranked.append(chunks[idx])
    if ranked:
        return ranked, "ok", None, retries, waited
    return chunks, "empty", None, retries, waited


def retrieve_ranked(project_id: str, question: str, settings_override: dict | None = None,
                    settings: dict | None = None) -> RetrievalResult:
    """
    The steps of retrieve_context_and_build_prompt, keeping the full ranked list.
    Pass `settings` (already merged) to skip the DB read, e.g. inside a run.
    """
    set_project_id(project_id)
    t0 = time.perf_counter()
    settings = settings or merge_settings(project_id, settings_override)
    document_ids = get_project_documents(project_id)

    chunks = SEARCH_STRATEGIES[settings["rag_strategy"]](question, document_ids, settings)
    t_search = time.perf_counter()
    search_ids = [c.get("id") for c in chunks]

    rerank_status, rerank_error, retries, waited = "disabled", None, 0, 0.0
    if settings.get("reranking_enabled", False) and chunks:
        chunks, rerank_status, rerank_error, retries, waited = _rerank(
            question, chunks, settings.get("reranking_model", "rerank-english-v3.0"))
    t_rerank = time.perf_counter()

    final = chunks[:settings["final_context_size"]]
    texts, images, tables, citations = separate_content_types(final)
    t_end = time.perf_counter()

    # Rate-limit waits are an eval artefact, so they are kept out of the latency numbers
    return RetrievalResult(
        settings=settings, search_ids=search_ids, ranked=chunks, final=final,
        texts=texts, images=images, tables=tables, citations=citations,
        rerank_status=rerank_status, rerank_error=rerank_error, rerank_retries=retries,
        timings={"search": round(t_search - t0, 3),
                 "rerank": round(t_rerank - t_search - waited, 3),
                 "retrieval": round(t_end - t0 - waited, 3),
                 "rerank_wait": round(waited, 3)},
    )


# Settings that decide the ranked list. A saved run can be reused only if these match exactly;
# final_context_size may differ (it only cuts the saved list).
RANKING_KEYS = ("rag_strategy", "chunks_per_search", "similarity_threshold", "number_of_queries",
                "reranking_enabled", "reranking_model", "vector_weight", "keyword_weight")


def retrieval_from_saved(saved: dict, settings: dict) -> RetrievalResult:
    """
    Rebuild a RetrievalResult from a saved run's record instead of calling search and rerank
    (--reuse-retrieval). The ranked ids are reused as saved; the final context is the first
    final_context_size of them, fetched from the DB and split exactly like the app does.
    Timings are the saved ones, so latency numbers stay those of the original retrieval.
    """
    from src.services.database import supabase
    final_ids = saved["ranked_chunk_ids"][:settings["final_context_size"]]
    rows = []
    if final_ids:
        rows = (supabase.table("document_chunks").select("id, document_id, page_number, original_content")
                .in_("id", final_ids).execute().data)
    by_id = {r["id"]: r for r in rows}
    missing = [i for i in final_ids if i not in by_id]
    if missing:
        raise RuntimeError(f"{len(missing)} saved chunk ids no longer in the DB (was the project re-indexed?)")
    final = [by_id[i] for i in final_ids]
    texts, images, tables, citations = separate_content_types(final)
    ranked = [{"id": c, "document_id": d} for c, d in zip(saved["ranked_chunk_ids"], saved["ranked_document_ids"])]
    return RetrievalResult(
        settings=settings, search_ids=saved["search_chunk_ids"], ranked=ranked, final=final,
        texts=texts, images=images, tables=tables, citations=citations,
        rerank_status=saved["rerank_status"], rerank_error=saved.get("rerank_error"),
        rerank_retries=saved.get("rerank_retries", 0),
        timings={k: saved["timings"][k] for k in ("search", "rerank", "retrieval", "rerank_wait")
                 if k in saved["timings"]},
    )


def load_reuse(name: str, project_id: str, split: str, settings: dict) -> dict[str, dict]:
    """Saved records of run `name` by question id, after checking they were ranked the same way."""
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"--reuse-retrieval: {path} missing")
    saved = json.loads(path.read_text())
    problems = []
    if saved["project_id"] != project_id:
        problems.append("different project")
    if saved["split"] != split:
        problems.append(f"split {saved['split']} vs {split}")
    for k in RANKING_KEYS:
        if saved["settings"].get(k) != settings.get(k):
            problems.append(f"{k}: saved {saved['settings'].get(k)!r} vs {settings.get(k)!r}")
    if problems:
        raise SystemExit(f"--reuse-retrieval {name}: ranking settings differ: " + "; ".join(problems))
    bad = saved["stats"]["errors"] + saved["stats"]["rerank_failed"]
    if bad:
        raise SystemExit(f"--reuse-retrieval {name}: the saved run has errors or rerank failures ({bad})")
    return {r["id"]: r for r in saved["questions"] if not r["error"]}


def _sum_usage(usage_by_model: dict) -> dict:
    tokens = {"input": 0, "output": 0, "total": 0}
    for u in usage_by_model.values():
        tokens["input"] += u.get("input_tokens", 0)
        tokens["output"] += u.get("output_tokens", 0)
        tokens["total"] += u.get("total_tokens", 0)
    return tokens


def answer_question(project_id: str, question: str, *, settings_override: dict | None = None,
                    settings: dict | None = None, generate: bool = True, guardrail: bool = False,
                    saved: dict | None = None) -> dict:
    """Run one question through the core RAG path. Returns ids, answer, contexts, tokens, timings.
    With `saved` (a record of a saved run), retrieval is rebuilt from it instead of searched."""
    t0 = time.perf_counter()
    out = {
        "answer": None, "search_chunk_ids": [], "ranked_chunk_ids": [], "ranked_document_ids": [],
        "final_chunk_ids": [], "contexts": [], "rerank_status": None, "rerank_error": None,
        "rerank_retries": 0, "guardrail_blocked": False,
        "tokens": {"input": 0, "output": 0, "total": 0},
        "tokens_retrieval": {"input": 0, "output": 0, "total": 0}, "n_images": 0,
        "timings": {}, "settings": None,
    }

    if guardrail:
        check = check_input_guardrails(question)
        out["timings"]["guardrail"] = round(time.perf_counter() - t0, 3)
        if not check.is_safe:
            out["guardrail_blocked"] = True
            out["answer"] = GUARDRAIL_ANSWER.format(reason=check.reason)
            out["timings"]["total"] = round(time.perf_counter() - t0, 3)
            return out

    if saved is not None:
        r = retrieval_from_saved(saved, settings)
        out["tokens_retrieval"] = saved.get("tokens_retrieval")  # cost of the original retrieval
        out["retrieval_reused"] = True
    else:
        # Separate callback so the multi-query LLM call is counted apart from generation
        with get_usage_metadata_callback() as cb_retrieval:
            r = retrieve_ranked(project_id, question, settings_override, settings)
        out["tokens_retrieval"] = _sum_usage(cb_retrieval.usage_metadata)
        out["retrieval_reused"] = False
    out["n_images"] = len(r.images)
    out.update({
        "search_chunk_ids": r.search_ids,
        "ranked_chunk_ids": [c.get("id") for c in r.ranked],
        "ranked_document_ids": [c.get("document_id") for c in r.ranked],
        "final_chunk_ids": [c.get("id") for c in r.final],
        "contexts": r.texts + r.tables,
        "rerank_status": r.rerank_status,
        "rerank_error": r.rerank_error,
        "rerank_retries": r.rerank_retries,
        "settings": r.settings,
    })
    out["timings"].update(r.timings)

    if generate:
        t_gen = time.perf_counter()
        if not r.texts:
            out["answer"] = NO_CONTEXT_ANSWER
        else:
            with get_usage_metadata_callback() as cb:
                out["answer"] = prepare_prompt_and_invoke_llm(question, r.texts, r.images, r.tables)
            out["tokens"] = _sum_usage(cb.usage_metadata)
        out["timings"]["generation"] = round(time.perf_counter() - t_gen, 3)

    out["timings"]["total"] = round(time.perf_counter() - t0 - out["timings"].get("rerank_wait", 0), 3)
    return out


# ============================================================================ metrics

def first_rank(ids: list[str], targets: set[str]) -> int | None:
    """1-based rank of the first id in targets, or None."""
    for i, x in enumerate(ids, 1):
        if x in targets:
            return i
    return None


def _score(records: list[dict]) -> dict:
    """Retrieval metrics over records that have chunk_rank / paper_rank / context_hit."""
    n = len(records)
    if not n:
        return {"n": 0}
    m = {"n": n}
    for prefix, key in (("", "chunk_rank"), ("paper_", "paper_rank")):
        ranks = [r[key] for r in records]
        for k in HIT_KS:
            m[f"{prefix}hit@{k}"] = round(sum(1 for x in ranks if x and x <= k) / n, 4)
        m[f"{prefix}mrr"] = round(sum(1 / x for x in ranks if x) / n, 4)
    m["context_hit"] = round(sum(r["context_hit"] for r in records) / n, 4)
    m["pool_hit"] = round(sum(r["pool_hit"] for r in records) / n, 4)
    return m


BREAKDOWNS = (("source", "by_source"), ("type", "by_type"), ("modality", "by_modality"))


def _grouped(records: list[dict], score_fn) -> dict:
    """score_fn over all records, and per source / type / modality."""
    out = {"overall": score_fn(records)}
    for key, bucket in BREAKDOWNS:
        groups = defaultdict(list)
        for r in records:
            groups[r[key]].append(r)
        out[bucket] = {g: score_fn(rs) for g, rs in sorted(groups.items())}
    return out


def retrieval_metrics(records: list[dict]) -> dict:
    """Overall and by source / type / modality, over the scored (answerable + matched, no error) records."""
    return _grouped([r for r in records if r["scored"]], _score)


def is_refusal(answer: str | None) -> bool | None:
    """True if the answer is the app's refusal (or the no-context answer); None if nothing was generated."""
    if answer is None:
        return None
    a = answer.strip().lower().replace("’", "'")
    return a == NO_CONTEXT_ANSWER.lower() or any(m in a for m in REFUSAL_MARKERS)


def _refusal_score(records: list[dict]) -> dict:
    ans = [r for r in records if r["answerable"]]
    una = [r for r in records if not r["answerable"]]
    fr = [r for r in ans if r["refused"]]
    return {
        "answerable_n": len(ans), "unanswerable_n": len(una),
        "refusal_accuracy": round(sum(r["refused"] for r in una) / len(una), 4) if una else None,
        "false_refusal_rate": round(len(fr) / len(ans), 4) if ans else None,
        "false_refusals": len(fr),
        # gold in context = the generator refused despite the evidence; not in context = retrieval miss
        "false_refusals_gold_in_context": sum(1 for r in fr if r["matched"] and r["context_hit"]),
        "false_refusals_gold_not_in_context": sum(1 for r in fr if r["matched"] and not r["context_hit"]),
        "false_refusals_unmatched": sum(1 for r in fr if not r["matched"]),
    }


def refusal_metrics(records: list[dict]) -> dict | None:
    """A3: refusal accuracy (unanswerable refused) and false-refusal rate (answerable refused)."""
    gen = [r for r in records if r.get("refused") is not None and not r["error"] and not r["guardrail_blocked"]]
    return _grouped(gen, _refusal_score) if gen else None


_tokenizer = None


def _count_tokens(text: str) -> int:
    global _tokenizer
    if _tokenizer is None:
        import tiktoken
        _tokenizer = tiktoken.get_encoding("cl100k_base")  # text-embedding-3-* tokenizer
    return len(_tokenizer.encode(text))


def _usd(model: str, tokens: dict | None) -> float | None:
    if tokens is None:
        return None
    p_in, p_out = PRICE_PER_M[model]
    return (tokens.get("input", 0) * p_in + tokens.get("output", 0) * p_out) / 1e6


def query_cost(rec: dict, settings: dict) -> dict:
    """
    A4: dollars for one question, by part. Generation and the multi-query LLM call use the token
    counts from the API. Query embeddings are an estimate (question tokens x number of queries;
    the variations are assumed as long as the question). Rerank is the Cohere LIST price.
    A part is None when it can't be recovered (retrieval tokens of old multi-query runs).
    """
    mq = settings["rag_strategy"].startswith("multi-query")
    emb_model = settings.get("embedding_model", "text-embedding-3-large")
    n_queries = settings["number_of_queries"] if mq else 1
    reranked = rec.get("rerank_status") in ("ok", "empty")
    cost = {
        "generation": _usd(GENERATOR_MODEL, rec["tokens"]),
        "retrieval_llm": _usd(GENERATOR_MODEL, rec.get("tokens_retrieval")),
        "embeddings_est": _count_tokens(rec["question"]) * n_queries * PRICE_PER_M[emb_model][0] / 1e6,
        "rerank_list": (math.ceil(len(rec["search_chunk_ids"]) / RERANK_DOCS_PER_SEARCH) * RERANK_USD_PER_SEARCH
                        if reranked else 0.0),
    }
    cost["total"] = sum(v for v in cost.values() if v is not None)
    return {k: (round(v, 7) if v is not None else None) for k, v in cost.items()}


def run_cost(records: list[dict]) -> dict | None:
    """Cost per query over the questions that ran without error (guardrail calls are not counted)."""
    ok = [r for r in records if not r["error"] and r.get("cost_usd")]
    if not ok:
        return None
    per_q = [r["cost_usd"]["total"] for r in ok]
    parts = {}
    for k in COST_PARTS:
        xs = [r["cost_usd"][k] for r in ok]
        parts[k] = round(sum(xs), 5) if all(x is not None for x in xs) else None
    return {
        "n": len(ok),
        "total_usd": round(sum(per_q), 5),
        "parts_usd": parts,
        "usd_per_query": {"p50": _pct(per_q, 0.5, 7), "mean": round(sum(per_q) / len(per_q), 7),
                          "p95": _pct(per_q, 0.95, 7), "max": round(max(per_q), 7)},
        "complete": all(v is not None for v in parts.values()),
        "note": "rerank at Cohere list price; query embeddings estimated; Ragas judge cost is under `ragas`",
    }


def derive(rec: dict, settings: dict) -> dict:
    """Fields computed from a record's saved ids and answer (used by runs and by --rescore)."""
    gold_ids = set(rec["gold_chunk_ids"])
    rec["modality"] = MODALITY.get(rec["source"], rec["source"])
    # Errored questions are not scored (they show up in stats.errors instead)
    rec["scored"] = bool(rec["answerable"] and rec["matched"] and not rec["error"])
    rec["chunk_rank"] = first_rank(rec["ranked_chunk_ids"], gold_ids)
    rec["paper_rank"] = first_rank(rec["ranked_document_ids"], {rec["gold_document_id"]})
    rec["context_hit"] = bool(gold_ids & set(rec["final_chunk_ids"]))
    rec["pool_hit"] = bool(gold_ids & set(rec["search_chunk_ids"]))   # B1: in the candidates before rerank
    rec["refused"] = is_refusal(rec.get("answer"))
    rec["cost_usd"] = None if rec["error"] else query_cost(rec, settings)
    return rec


def _pct(xs: list[float], p: float, digits: int = 3) -> float:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], digits)


def run_stats(records: list[dict]) -> dict:
    ok = [r for r in records if not r.get("error")]
    stats = {
        "errors": len(records) - len(ok),
        "rerank_failed": sum(1 for r in ok if r["rerank_status"] == "failed"),
        "rerank_empty": sum(1 for r in ok if r["rerank_status"] == "empty"),
        "rerank_retries": sum(r["rerank_retries"] for r in ok),
        "rerank_wait_seconds": round(sum(r["timings"].get("rerank_wait", 0) for r in ok), 1),
        "empty_retrieval": sum(1 for r in ok if not r["guardrail_blocked"] and not r["ranked_chunk_ids"]),
        "guardrail_blocked": sum(1 for r in ok if r["guardrail_blocked"]),
        "tokens": {k: sum(r["tokens"][k] for r in ok) for k in ("input", "output", "total")},
        "latency": {},
    }
    for stage in ("search", "rerank", "retrieval", "generation", "total"):
        xs = [r["timings"][stage] for r in ok if stage in r["timings"]]
        if xs:
            stats["latency"][stage] = {"p50": _pct(xs, 0.5), "p95": _pct(xs, 0.95)}
    stats["ragas_failed"] = sum(len(r.get("ragas_errors") or {}) for r in records)
    return stats


# ============================================================================ answer quality (Ragas)

def _ragas_eligible(rec: dict) -> bool:
    """Answerable, has a reference and an answer, no error, not blocked by the guardrail, not a
    refusal (refusals are scored inconsistently by Ragas and are reported by refusal_metrics)."""
    return bool(rec["answerable"] and rec["reference_answer"] and rec["answer"]
                and not rec["error"] and not rec["guardrail_blocked"] and not rec.get("refused"))


def _count_usage(client, usage: dict) -> None:
    """Wrap the eval's own OpenAI client so every judge / embedding call adds its token usage.
    Must run before llm_factory (instructor captures chat.completions.create when it patches)."""
    chat_create, emb_create = client.chat.completions.create, client.embeddings.create

    async def counted_chat(*args, **kwargs):
        resp = await chat_create(*args, **kwargs)
        if getattr(resp, "usage", None):
            usage["judge_input"] += resp.usage.prompt_tokens or 0
            usage["judge_output"] += resp.usage.completion_tokens or 0
        return resp

    async def counted_emb(*args, **kwargs):
        resp = await emb_create(*args, **kwargs)
        if getattr(resp, "usage", None):
            usage["embedding"] += resp.usage.prompt_tokens or 0
        return resp

    client.chat.completions.create = counted_chat
    client.embeddings.create = counted_emb


async def _ragas_score_all(records: list[dict]) -> dict:
    """Add `ragas` ({metric: score or None}) and `ragas_errors` to every record, in place.
    Returns the judge's token usage."""
    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerCorrectness, AnswerRelevancy, Faithfulness

    client = AsyncOpenAI(api_key=app_config["openai_api_key"])
    usage = {"judge_input": 0, "judge_output": 0, "embedding": 0}
    _count_usage(client, usage)
    llm = llm_factory(RAGAS_JUDGE_MODEL, client=client, max_tokens=RAGAS_JUDGE_MAX_TOKENS)
    embeddings = embedding_factory("openai", model=RAGAS_EMBEDDING_MODEL, client=client,
                                   interface="modern")
    metrics = {
        "faithfulness": Faithfulness(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
        "answer_correctness": AnswerCorrectness(llm=llm, embeddings=embeddings),
    }
    sem = asyncio.Semaphore(RAGAS_CONCURRENCY)

    async def score_one(rec: dict):
        rec["ragas"], rec["ragas_errors"] = None, {}
        if not _ragas_eligible(rec):
            return
        inputs = {
            "faithfulness": {"user_input": rec["question"], "response": rec["answer"],
                             "retrieved_contexts": rec["contexts"]},
            "answer_relevancy": {"user_input": rec["question"], "response": rec["answer"]},
            "answer_correctness": {"user_input": rec["question"], "response": rec["answer"],
                                   "reference": rec["reference_answer"]},
        }
        if not rec["contexts"]:  # nothing retrieved: no contexts to check claims against
            inputs.pop("faithfulness")
        scores = {m: None for m in RAGAS_METRICS}
        async with sem:
            results = await asyncio.gather(*(metrics[m].ascore(**kw) for m, kw in inputs.items()),
                                           return_exceptions=True)
        for m, res in zip(inputs, results):
            if isinstance(res, Exception):
                rec["ragas_errors"][m] = f"{type(res).__name__}: {res}"
            elif res.value is not None:
                scores[m] = round(float(res.value), 4)
        rec["ragas"] = scores

    done = 0

    async def tracked(rec: dict):
        nonlocal done
        await score_one(rec)
        done += 1
        if done % 10 == 0 or done == len(records):
            print(f"  ragas {done}/{len(records)}")

    await asyncio.gather(*(tracked(r) for r in records))
    await client.close()
    return usage


def ragas_cost(usage: dict) -> float:
    judge_in, judge_out = PRICE_PER_M[RAGAS_JUDGE_MODEL]
    return round((usage["judge_input"] * judge_in + usage["judge_output"] * judge_out
                  + usage["embedding"] * PRICE_PER_M[RAGAS_EMBEDDING_MODEL][0]) / 1e6, 5)


def _answer_score(records: list[dict]) -> dict:
    """Mean of each Ragas metric over records that have a score for it, with its count."""
    m = {"n": len(records)}
    for metric in RAGAS_METRICS:
        xs = [r["ragas"][metric] for r in records if r["ragas"][metric] is not None]
        m[metric] = round(sum(xs) / len(xs), 4) if xs else None
        m[f"{metric}_n"] = len(xs)
    return m


def answer_metrics(records: list[dict]) -> dict:
    """Ragas means overall and by source / type / modality, over the scored records. Refused
    answers are left out (see refusal_metrics), so a config can't look better by refusing more."""
    return _grouped([r for r in records if r.get("ragas") and not r.get("refused")], _answer_score)


# ============================================================================ experiment run

def load_gold(project_name: str) -> dict:
    path = GOLD_DIR / f"{project_name}.json"
    if not path.exists():
        raise SystemExit(f"{path} missing: run `python -m evaluation.open_ragbench.gold --write` first")
    return json.loads(path.read_text())


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=HERE, check=True).stdout.strip()
    except Exception:
        return None


def _evaluate_one(project_id: str, q: dict, settings: dict, generate: bool, guardrail: bool,
                  saved: dict | None = None) -> dict:
    gold_ids = {c["id"] for c in q["gold_chunks"]}
    rec = {
        "id": q["id"], "question": q["question"], "reference_answer": q["reference_answer"],
        "source": q["source"], "type": q["type"], "answer_type": q["answer_type"],
        "gold_doc": q["gold_doc"], "gold_document_id": q["gold_document_id"],
        "answerable": q["answerable"], "matched": q["matched"],
        "gold_chunk_ids": sorted(gold_ids), "error": None,
    }
    try:
        res = answer_question(project_id, q["question"], settings=settings,
                              generate=generate, guardrail=guardrail, saved=saved)
        res.pop("settings")
        rec.update(res)
    except Exception as e:
        rec.update({"error": f"{type(e).__name__}: {e}", "answer": None, "search_chunk_ids": [],
                    "ranked_chunk_ids": [], "ranked_document_ids": [], "final_chunk_ids": [],
                    "contexts": [], "rerank_status": None, "rerank_error": None, "rerank_retries": 0,
                    "guardrail_blocked": False, "tokens": {"input": 0, "output": 0, "total": 0},
                    "tokens_retrieval": {"input": 0, "output": 0, "total": 0}, "n_images": 0,
                    "timings": {}})
    return derive(rec, settings)


def run_experiment(cfg: dict, project_name: str, workers: int, limit: int | None, overwrite: bool,
                   reuse: str | None = None) -> Path:
    name = cfg["name"] + (f"-limit{limit}" if limit else "")
    path = RESULTS_DIR / f"{name}.json"
    if path.exists() and not overwrite:
        raise SystemExit(f"{path} exists. Rename the config or pass --overwrite.")

    gold = load_gold(project_name)
    project_id = gold["project_id"]
    settings = merge_settings(project_id, cfg["settings"])
    generate = not cfg["retrieval_only"]
    questions = [q for q in gold["questions"] if q["split"] == cfg["split"]]
    if not generate:  # unanswerable questions have nothing to score without an answer
        questions = [q for q in questions if q["answerable"]]
    if limit:
        questions = questions[:limit]

    print(f"Run '{name}': {len(questions)} {cfg['split']} questions, retrieval_only={cfg['retrieval_only']}, "
          f"guardrail={cfg['guardrail']}, workers={workers}")
    print(f"Overrides: {cfg['settings'] or '(none, DB settings)'}")
    if settings["chunks_per_search"] < max(HIT_KS):
        print(f"Note: chunks_per_search={settings['chunks_per_search']} < {max(HIT_KS)}; "
              f"Hit@k above it can't improve.")
    saved = load_reuse(reuse, project_id, cfg["split"], settings) if reuse else {}
    if reuse:  # loaded before this run's file can overwrite it (reuse name == run name is fine)
        live = sum(1 for q in questions if q["id"] not in saved)
        print(f"Reusing retrieval of '{reuse}' for {len(questions) - live} questions; "
              f"{live} searched and reranked live")

    records, t0 = [], time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_evaluate_one, project_id, q, settings, generate, cfg["guardrail"],
                               saved.get(q["id"]))
                   for q in questions]
        for i, f in enumerate(as_completed(futures), 1):
            records.append(f.result())
            if i % 10 == 0 or i == len(futures):
                print(f"  {i}/{len(futures)} done ({time.perf_counter() - t0:.0f}s)")
    order = {q["id"]: i for i, q in enumerate(questions)}
    records.sort(key=lambda r: order[r["id"]])

    ragas_seconds, ragas_usage = None, None
    if generate:
        print(f"Scoring answers with Ragas (judge {RAGAS_JUDGE_MODEL})...")
        t_ragas = time.perf_counter()
        ragas_usage = asyncio.run(_ragas_score_all(records))
        ragas_seconds = round(time.perf_counter() - t_ragas, 1)

    answerable = [r for r in records if r["answerable"]]
    result = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "project_name": project_name,
        "project_id": project_id,
        "config": {k: v for k, v in cfg.items() if k != "name"},
        "split": cfg["split"],
        "limit": limit,
        "gold_threshold": gold["threshold"],
        "reused_retrieval_from": reuse,
        "settings": {k: settings[k] for k in sorted(TUNABLE_KEYS) if k in settings},
        "counts": {
            "questions": len(records),
            "answerable": len(answerable),
            "scored": sum(r["scored"] for r in records),
            "unmatched_left_out": sum(1 for r in answerable if not r["matched"]),
            "unanswerable": len(records) - len(answerable),
        },
        "metrics": retrieval_metrics(records),
        "refusal_metrics": refusal_metrics(records),
        "answer_metrics": answer_metrics(records) if generate else None,
        "ragas": ({"judge_model": RAGAS_JUDGE_MODEL, "embedding_model": RAGAS_EMBEDDING_MODEL,
                   "seconds": ragas_seconds, "tokens": ragas_usage,
                   "cost_usd": ragas_cost(ragas_usage)} if generate else None),
        "cost": run_cost(records),
        "stats": run_stats(records),
        "wall_seconds": round(time.perf_counter() - t0, 1),
        "questions": records,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=str))
    print_summary(result)
    print(f"\nWrote {path}")
    return path


# ============================================================================ printing

def _f(x, fmt: str = ">6.3f", width: int = 6) -> str:
    return f"{x:{fmt}}" if x is not None else f"{'-':>{width}}"


def _metric_header(first: str = "") -> str:
    ks = " ".join(f"{'H@' + str(k):>6}" for k in HIT_KS)
    return f"  {first:<22} {'n':>4} {ks} {'MRR':>6} {'ctxHit':>7} {'pool':>6} {'pH@1':>6} {'pMRR':>6}"


def _metric_row(label: str, m: dict) -> str:
    if not m.get("n"):
        return f"  {label:<22} {0:>4}"
    cells = " ".join(f"{m[f'hit@{k}']:>6.3f}" for k in HIT_KS)
    return (f"  {label:<22} {m['n']:>4} {cells} {m['mrr']:>6.3f} {m['context_hit']:>7.3f}"
            f" {_f(m.get('pool_hit'))} {m['paper_hit@1']:>6.3f} {m['paper_mrr']:>6.3f}")


def _delta_row(m: dict, ref: dict) -> str:
    """Differences in points (x100) vs the reference run, same columns as _metric_row."""
    if not m.get("n") or not ref.get("n"):
        return ""
    def d(k):
        if m.get(k) is None or ref.get(k) is None:
            return f"{'-':>6}"
        return f"{(m[k] - ref[k]) * 100:>+6.1f}"
    cells = " ".join(d(f"hit@{k}") for k in HIT_KS)
    return (f"  {'  Δ pts':<22} {'':>4} {cells} {d('mrr')} {d('context_hit'):>7} {d('pool_hit')}"
            f" {d('paper_hit@1')} {d('paper_mrr')}")


def _answer_header(first: str = "") -> str:
    return f"  {first:<22} {'n':>4} {'Faith':>6} {'Relev':>6} {'Corr':>6} {'RefAcc':>7} {'FalseRef':>8}"


def _answer_row(label: str, m: dict, refusal: dict | None = None) -> str:
    cells = " ".join(_f(m.get(x)) for x in RAGAS_METRICS)
    refusal = refusal or {}
    return (f"  {label:<22} {m.get('n', 0):>4} {cells} {_f(refusal.get('refusal_accuracy'), '>7.3f', 7)}"
            f" {_f(refusal.get('false_refusal_rate'), '>8.3f', 8)}")


def _cost_line(result: dict) -> str:
    c = result.get("cost")
    if not c:
        return "Cost: -"
    q = c["usd_per_query"]
    parts = ", ".join(f"{k} {'?' if v is None else f'${v:.4f}'}" for k, v in c["parts_usd"].items())
    rg = result.get("ragas") or {}
    judge = f" | Ragas judge ${rg['cost_usd']:.4f}" if rg.get("cost_usd") is not None else ""
    return (f"Cost per query: p50 ${q['p50']:.5f}, mean ${q['mean']:.5f}, max ${q['max']:.4f} | "
            f"run total ${c['total_usd']:.4f} ({parts}){judge}"
            + ("" if c["complete"] else "  [incomplete: some parts not recoverable for this run]"))


def print_summary(result: dict):
    c, m, s = result["counts"], result["metrics"], result["stats"]
    print(f"\n=== {result['name']} ({result['split']}) ===")
    print(f"Settings: {json.dumps(result['settings'])}")
    print(f"Questions {c['questions']} | scored {c['scored']} | unmatched left out "
          f"{c['unmatched_left_out']} | unanswerable {c['unanswerable']}")
    print("\nRetrieval (H@k, MRR by chunk; ctxHit = gold in final context; pool = gold among the search "
          "candidates before rerank; pH@1, pMRR by paper):")
    print(_metric_header())
    print(_metric_row("overall", m["overall"]))
    for bucket in ("by_modality", "by_source", "by_type"):
        for g, gm in m.get(bucket, {}).items():
            print(_metric_row(g, gm))
    am, rm = result.get("answer_metrics"), result.get("refusal_metrics")
    if am:
        print(f"\nAnswer quality (Ragas, judge {result['ragas']['judge_model']}, refused answers left out; "
              f"RefAcc = unanswerable refused, FalseRef = answerable refused):")
        print(_answer_header())
        print(_answer_row("overall", am["overall"], (rm or {}).get("overall")))
        for bucket in ("by_modality", "by_source", "by_type"):
            for g, gm in am.get(bucket, {}).items():
                print(_answer_row(g, gm, (rm or {}).get(bucket, {}).get(g)))
        if rm:
            o = rm["overall"]
            print(f"False refusals {o['false_refusals']}: gold in context {o['false_refusals_gold_in_context']} "
                  f"(generator), gold not in context {o['false_refusals_gold_not_in_context']} (retrieval), "
                  f"unmatched {o['false_refusals_unmatched']}")
        print(f"Ragas failed calls {s.get('ragas_failed', 0)} | Ragas time {result['ragas'].get('seconds')}s")
    print(f"\nErrors {s['errors']} | rerank failed {s['rerank_failed']} | rerank empty "
          f"{s['rerank_empty']} | rerank retries {s['rerank_retries']} (waited "
          f"{s['rerank_wait_seconds']}s, excluded from latency) | empty retrieval "
          f"{s['empty_retrieval']} | guardrail blocked {s['guardrail_blocked']}")
    print(f"Tokens (generation) {s['tokens']}")
    print(_cost_line(result))
    print(f"Latency {s['latency']}")
    if s["rerank_failed"] or s["errors"]:
        print("WARNING: errors or rerank failures present; metrics may not reflect these settings.")


def _load_result(name: str) -> dict | None:
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        print(f"  missing: {path}")
        return None
    return json.loads(path.read_text())


def compare(names: list[str], by: str | None = None, vs: str | None = "baseline"):
    """B3: one row per run (sorted by MRR) with deltas vs `vs`, answer quality, refusals, cost, latency."""
    if names == ["all"]:
        names = sorted(p.stem for p in RESULTS_DIR.glob("*.json"))
    rows = [r for r in (_load_result(n) for n in names) if r]
    if not rows:
        return
    rows.sort(key=lambda r: -r["metrics"]["overall"].get("mrr", 0))
    ref = next((r for r in rows if r["name"] == vs), None)
    bucket = f"by_{by}" if by else None

    print("Retrieval (Δ pts = difference vs " + (f"'{vs}'" if ref else "no reference") + "):")
    print(_metric_header("run"))
    for r in rows:
        print(_metric_row(r["name"][:22], r["metrics"]["overall"]))
        if ref and r is not ref:
            print(_delta_row(r["metrics"]["overall"], ref["metrics"]["overall"]))
        if bucket:
            for g, gm in r["metrics"].get(bucket, {}).items():
                print(_metric_row(f"  {g}"[:22], gm))
                if ref and r is not ref and g in ref["metrics"].get(bucket, {}):
                    print(_delta_row(gm, ref["metrics"][bucket][g]))

    gen = [r for r in rows if r.get("answer_metrics")]
    if gen:
        print("\nAnswer quality (Ragas, refused answers left out) and refusals:")
        print(_answer_header("run"))
        for r in gen:
            rm = r.get("refusal_metrics") or {}
            print(_answer_row(r["name"][:22], r["answer_metrics"]["overall"], rm.get("overall")))
            if bucket:
                for g, gm in r["answer_metrics"].get(bucket, {}).items():
                    print(_answer_row(f"  {g}"[:22], gm, rm.get(bucket, {}).get(g)))

    print("\nLatency p50 (retrieval is comparable across runs; total includes generation), cost per query:")
    print(f"  {'run':<22} {'retr p50':>9} {'total p50':>9} {'$/q p50':>9} {'$/q mean':>9}  overrides / notes")
    for r in rows:
        lat = r["stats"]["latency"]
        c = (r.get("cost") or {}).get("usd_per_query", {})
        notes = []
        if r["config"].get("retrieval_only"):
            notes.append("retrieval-only")
        if r.get("limit"):
            notes.append(f"limit={r['limit']}")
        if r.get("reused_retrieval_from"):
            notes.append(f"retrieval reused from {r['reused_retrieval_from']}")
        if r["stats"]["errors"] or r["stats"]["rerank_failed"]:
            notes.append(f"errors={r['stats']['errors']} rerank_failed={r['stats']['rerank_failed']}")
        if r.get("cost") and not r["cost"]["complete"]:
            notes.append("cost incomplete")
        print(f"  {r['name'][:22]:<22} {_f(lat.get('retrieval', {}).get('p50'), '>9.3f', 9)}"
              f" {_f(lat.get('total', {}).get('p50'), '>9.3f', 9)} {_f(c.get('p50'), '>9.5f', 9)}"
              f" {_f(c.get('mean'), '>9.5f', 9)}  {json.dumps(r['config'].get('settings', {}))}"
              + (f"  [{', '.join(notes)}]" if notes else ""))
    if any("pool_hit" not in r["metrics"]["overall"] for r in rows):
        print("NOTE: some runs predate pool hit / refusals / cost: run --rescore on them.")
    if len({r["split"] for r in rows}) > 1:
        print("WARNING: runs from different splits are not comparable.")
    if len({r["settings"]["chunks_per_search"] for r in rows}) > 1:
        print("WARNING: chunks_per_search differs; compare Hit@k only up to the smallest value.")


def rescore(name: str):
    """Recompute every derived field and metric of a saved run from its records. No API calls."""
    path = RESULTS_DIR / f"{name}.json"
    result = json.loads(path.read_text())
    settings = result["settings"]
    mq = settings["rag_strategy"].startswith("multi-query")
    for rec in result["questions"]:
        # Old runs: retrieval made no LLM call unless multi-query; that call's tokens weren't saved
        rec.setdefault("tokens_retrieval", None if mq else {"input": 0, "output": 0, "total": 0})
        rec.setdefault("n_images", None)
        derive(rec, settings)
    records = result["questions"]
    generated = not result["config"].get("retrieval_only")
    result["metrics"] = retrieval_metrics(records)
    result["refusal_metrics"] = refusal_metrics(records)
    result["answer_metrics"] = answer_metrics(records) if generated else None
    result["cost"] = run_cost(records)
    result["stats"] = run_stats(records)
    if result.get("ragas"):
        result["ragas"].setdefault("tokens", None)    # not recorded before A4
        result["ragas"].setdefault("cost_usd", None)
    result["rescored_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(result, indent=2, default=str))
    print_summary(result)
    print(f"\nRescored {path}")


def _bootstrap_ci(d: list[float], seed: int = 0) -> tuple[float, float]:
    import numpy as np
    arr = np.asarray(d, dtype=float)
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, len(arr), size=(BOOTSTRAP_SAMPLES, len(arr)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def _verdict(diff: float, lo: float, hi: float, name_b: str) -> str:
    if abs(diff) < TIE_POINTS or lo <= 0 <= hi:
        return "tie"
    return f"{name_b} better" if diff > 0 else f"{name_b} worse"


def paired(name_a: str, name_b: str):
    """
    B2: paired comparison of two runs on the questions both scored. Binary metrics: wins / losses
    (questions B gets right and A misses, and the reverse) with an exact McNemar p-value. All
    metrics: mean difference B - A with a paired bootstrap 95% CI. Verdict: tie if the gap is
    under TIE_POINTS or the CI includes 0.
    """
    from scipy.stats import binomtest
    a, b = _load_result(name_a), _load_result(name_b)
    if not a or not b:
        return
    if a["split"] != b["split"]:
        print("WARNING: different splits; the comparison is not meaningful.")
    if "pool_hit" not in a["metrics"]["overall"] or "pool_hit" not in b["metrics"]["overall"]:
        raise SystemExit("Run --rescore on both runs first.")
    A = {r["id"]: r for r in a["questions"]}
    B = {r["id"]: r for r in b["questions"]}
    ids = [i for i in A if i in B and A[i]["scored"] and B[i]["scored"]]
    print(f"Paired: {name_a} (A) vs {name_b} (B) on {len(ids)} questions scored in both "
          f"({b['split']}). Δ = B - A in points; tie if |Δ| < {TIE_POINTS * 100:.0f} or the CI includes 0.\n")
    print(f"  {'metric':<26} {'A':>6} {'B':>6} {'Δ pts':>7} {'95% CI':>15} {'B wins':>6} {'B loses':>7}"
          f" {'McNemar p':>9}  verdict")

    binary = {
        "hit@1": lambda r: r["chunk_rank"] == 1,
        "hit@5": lambda r: bool(r["chunk_rank"] and r["chunk_rank"] <= 5),
        "context_hit": lambda r: r["context_hit"],
        "pool_hit": lambda r: r["pool_hit"],
    }
    for name, fn in binary.items():
        xa, xb = [fn(A[i]) for i in ids], [fn(B[i]) for i in ids]
        wins = sum(1 for p, q in zip(xa, xb) if q and not p)
        losses = sum(1 for p, q in zip(xa, xb) if p and not q)
        p = binomtest(min(wins, losses), wins + losses, 0.5).pvalue if wins + losses else 1.0
        d = [int(q) - int(p_) for p_, q in zip(xa, xb)]
        diff = sum(d) / len(d)
        lo, hi = _bootstrap_ci(d)
        print(f"  {name:<26} {sum(xa) / len(ids):>6.3f} {sum(xb) / len(ids):>6.3f} {diff * 100:>+7.1f}"
              f" {f'[{lo * 100:+.1f}, {hi * 100:+.1f}]':>15} {wins:>6} {losses:>7} {p:>9.3f}  "
              f"{_verdict(diff, lo, hi, name_b)}")

    rr = lambda r: 1 / r["chunk_rank"] if r["chunk_rank"] else 0.0
    continuous = [("mrr", ids, rr)]
    # Answer quality: answerable questions both runs answered (not refused) and Ragas scored
    for metric in RAGAS_METRICS:
        both = [i for i in A if i in B and (A[i].get("ragas") or {}).get(metric) is not None
                and (B[i].get("ragas") or {}).get(metric) is not None
                and not A[i].get("refused") and not B[i].get("refused")]
        if both:
            continuous.append((metric, both, lambda r, m=metric: r["ragas"][m]))
    for name, qids, fn in continuous:
        xa, xb = [fn(A[i]) for i in qids], [fn(B[i]) for i in qids]
        d = [q - p for p, q in zip(xa, xb)]
        diff = sum(d) / len(d)
        lo, hi = _bootstrap_ci(d)
        label = name if qids is ids else f"{name} (n={len(qids)})"
        print(f"  {label:<26} {sum(xa) / len(qids):>6.3f} {sum(xb) / len(qids):>6.3f} {diff * 100:>+7.1f}"
              f" {f'[{lo * 100:+.1f}, {hi * 100:+.1f}]':>15} {'':>6} {'':>7} {'':>9}  "
              f"{_verdict(diff, lo, hi, name_b)}")

    ra, rb = (a.get("refusal_metrics") or {}).get("overall"), (b.get("refusal_metrics") or {}).get("overall")
    if ra and rb:
        print(f"\n  Refusals: A refuses {ra['refusal_accuracy']:.3f} of unanswerable / {ra['false_refusal_rate']:.3f} "
              f"of answerable; B {rb['refusal_accuracy']:.3f} / {rb['false_refusal_rate']:.3f}")
    ca, cb = (a.get("cost") or {}).get("usd_per_query"), (b.get("cost") or {}).get("usd_per_query")
    if ca and cb and bool(a["config"].get("retrieval_only")) == bool(b["config"].get("retrieval_only")):
        print(f"  Cost per query (mean): A ${ca['mean']:.5f}, B ${cb['mean']:.5f}")
    la, lb = a["stats"]["latency"].get("retrieval", {}), b["stats"]["latency"].get("retrieval", {})
    if la and lb:
        print(f"  Retrieval latency p50: A {la['p50']}s, B {lb['p50']}s")


def show_question(project_name: str, question_id: str, override: dict, generate: bool, guardrail: bool):
    gold = load_gold(project_name)
    q = next((x for x in gold["questions"] if x["id"] == question_id), None)
    if q is None:
        raise SystemExit(f"Question {question_id} not in gold/{project_name}.json")
    gold_ids = {c["id"] for c in q["gold_chunks"]}
    res = answer_question(gold["project_id"], q["question"], settings_override=override,
                          generate=generate, guardrail=guardrail)

    print(f"Q [{q['source']}/{q['type']}/{q['split']}]: {q['question']}")
    print(f"Reference: {q['reference_answer']}")
    print(f"Gold chunks: {len(gold_ids)} (answerable={q['answerable']}, matched={q['matched']})")
    if res["settings"]:
        print(f"\nSettings: {json.dumps({k: res['settings'][k] for k in sorted(TUNABLE_KEYS)})}")
    print(f"Rerank: {res['rerank_status']}" + (f"  error: {res['rerank_error']}" if res["rerank_error"] else ""))
    if res["guardrail_blocked"]:
        print("Guardrail: BLOCKED")
    final = set(res["final_chunk_ids"])
    print("\nRanked (* = gold chunk, > = in final context, p = from gold paper):")
    for i, (cid, did) in enumerate(zip(res["ranked_chunk_ids"], res["ranked_document_ids"]), 1):
        flags = ("*" if cid in gold_ids else " ") + (">" if cid in final else " ") + \
                ("p" if did == q["gold_document_id"] else " ")
        print(f"  {i:>2} {flags} {cid}")
    print(f"\nChunk rank: {first_rank(res['ranked_chunk_ids'], gold_ids)}  "
          f"Paper rank: {first_rank(res['ranked_document_ids'], {q['gold_document_id']})}")
    print(f"\nAnswer: {res['answer']}")
    print(f"Tokens: {res['tokens']}")
    print(f"Timings: {res['timings']}")


# ============================================================================ CLI

def main():
    parser = argparse.ArgumentParser(
        description="Open RAGBench eval: run an experiment config through the core RAG path, "
                    "score retrieval, compare runs. See the module docstring for details.",
    )
    parser.add_argument("--config", help="Experiment YAML (configs/<name>.yaml)")
    parser.add_argument("--compare", nargs="+", metavar="NAME", help="Compare saved runs ('all' = every run)")
    parser.add_argument("--by", choices=["modality", "source", "type"], help="--compare: also print these groups")
    parser.add_argument("--vs", default="baseline", help="--compare: reference run for the deltas")
    parser.add_argument("--paired", nargs=2, metavar=("A", "B"), help="Paired comparison of two saved runs")
    parser.add_argument("--rescore", nargs="+", metavar="NAME", help="Recompute metrics of saved runs (no API calls)")
    parser.add_argument("--question-id", help="Inspect one question (uses --config settings if given)")
    parser.add_argument("--retrieval-only", action="store_true", help="--question-id only: skip generation")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, help="Only the first N questions (quick trial)")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing results file")
    parser.add_argument("--reuse-retrieval", metavar="NAME",
                        help="--config: take each question's ranked list from saved run NAME instead of "
                             "searching and reranking again (questions not in NAME run live)")
    parser.add_argument("--project-name", default=EVAL_PROJECT_NAME)
    args = parser.parse_args()

    if args.compare:
        compare(args.compare, args.by, args.vs)
    elif args.paired:
        paired(*args.paired)
    elif args.rescore:
        for name in args.rescore:
            rescore(name)
    elif args.question_id:
        cfg = load_config(args.config) if args.config else {"settings": {}, "guardrail": False}
        show_question(args.project_name, args.question_id, cfg["settings"],
                      not args.retrieval_only, cfg["guardrail"])
    elif args.config:
        run_experiment(load_config(args.config), args.project_name, args.workers, args.limit, args.overwrite,
                       args.reuse_retrieval)
    else:
        parser.error("give --config, --compare, --paired, --rescore or --question-id")


if __name__ == "__main__":
    main()
