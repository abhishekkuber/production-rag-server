# Phase 1, step 2: index the Open RAGBench subset into an eval project

> Working notes kept during the eval: the plan, cost approvals and the run order. The write-up for readers is [documentation/EVALUATION.md](../../../documentation/EVALUATION.md).

## Context

The eval moved from FinanceBench to a seeded subset of Open RAGBench (arXiv PDFs), because indexing all the FinanceBench 10-Ks costs too much. The PDFs and questions are now on disk. The next blocker is getting them into Supabase through the **real** ingestion pipeline, without the UI, Clerk, S3 or Celery. `project_documents` needs a `project_id`, a `clerk_id` (a foreign key to `users`) and a NOT NULL `s3_key`. The plan is to create those rows directly with the service-role client, then call `process_document` on the local file. The result is one eval project holding 40 indexed papers, plus a mapping file the eval runner will use later.

## What we have so far

All of this is under `server/evaluation/` and is git-ignored. It was produced by `open_ragbench/download.py` with seed 42.

| Item | Location | Contents |
|---|---|---|
| PDFs to index | `open_ragbench/data/pdfs/` | 40 arXiv PDFs (20 gold + 20 distractor), 88 MB, all checked as real PDFs |
| Gold-section source | `open_ragbench/data/corpus/` | The dataset's own parsed JSON for the 20 gold papers. Used only to match gold sections to our chunks, never indexed. |
| Questions | `open_ragbench/data/questions.jsonl` | 206 questions: 186 answerable (dev 112 / test 74) + 20 unanswerable from 5 held-out papers (dev 12 / test 8). By source: 108 text, 42 text+image, 23 text+table+image, 13 text+table. By type: 100 abstractive, 86 extractive. |
| Manifest | `open_ragbench/data/manifest.json` | Arguments, paper roles (gold / distractor / held_out), SHA-256 per file |
| Raw dataset files | `open_ragbench/data/raw/` | queries, answers, qrels, pdf_urls |

Environment: `.env` points at **local** Supabase (`127.0.0.1:54321`, started with `start_db.sh`), so eval data never reaches the cloud database. LangSmith tracing is on, with project `production-rag`.

## Implementation (this step)

### 1. Let ingestion read a local file
- `src/rag/ingestion/partition.py` `download_and_partition(document_id, document, local_path=None)`:
  - If `local_path` is set, skip the S3 download and pass that path to `partition_document`.
  - Do **not** `os.remove` it, because it's the source file.
  - The file type comes from `document["filename"]` as it does now.
- `src/rag/ingestion/index.py` `process_document(document_id, local_path=None)` passes the argument through.
- The Celery task (`src/services/celery.py:59`) and the routes stay as they are, since the default is `None`.

### 2. Share the default project settings
- Move the settings dict from `create_project` (`src/routes/projects.py:79`) into a constant `DEFAULT_PROJECT_SETTINGS`, in a new `src/config/project_defaults.py`. `create_project` uses that constant, so it behaves exactly as before.
- The eval project uses the defaults with `agent_type="simple"` (gap #6: no web search). All other values stay at the current hand-picked baseline.

### 3. `evaluation/open_ragbench/ingest.py`
Run from `server/` with: `python -m evaluation.open_ragbench.ingest [--project-name open-ragbench-baseline] [--limit N] [--papers id ...] [--workers 2]`

1. **Before importing `src`**, set `os.environ.setdefault("LANGSMITH_PROJECT", "knowledgedock-eval")`. This keeps the summary-LLM traces out of the `production-rag` project. `load_dotenv` doesn't override variables that are already set.
2. **User:** upsert `users(clerk_id="eval_open_ragbench")`.
3. **Project:** look it up by `(clerk_id, name)`, or create it plus its `project_settings` row from `DEFAULT_PROJECT_SETTINGS` and the eval override.
4. **Papers:** read gold and distractor ids from `manifest.json`, then apply `--papers` or `--limit` (gold papers first, so a trial run has questions to check).
5. **Each paper:**
   - Look up the `project_documents` row by `(project_id, filename)`. If it's `completed`, skip it.
   - If a row exists but isn't completed, delete it. The delete cascades to any chunks it left behind, because `process_document` raises without cleaning up and vectorization inserts one row at a time.
   - Insert a new row:
     - `filename`: `{paper_id}.pdf`
     - `file_size`: from disk
     - `file_type`: `application/pdf`, as the UI sends it
     - `s3_key`: `local://open_ragbench/{paper_id}.pdf`
     - `source_type`: `file`
     - `clerk_id`: the eval user
   - Call `process_document(doc_id, local_path=...)` and time it.
6. **Concurrency:** a `ThreadPoolExecutor` with `--workers` (default 2). `hi_res` parsing is CPU-bound, and Celery already runs this code in a threads pool, so it's safe to run in threads. A failure in one paper is logged and the rest continue.
7. **Output:** `open_ragbench/data/ingest_runs/<project-name>.json` with:
   - `project_id`, `clerk_id`, the settings used and the git commit
   - per paper: `role`, `document_id`, `status`, `seconds`, `chunks`, and `elements_found` read from `processing_details`
   - failures
   - totals: papers, chunks, how many chunks contain a table or image (from `document_chunks.type`), and p50/max seconds per paper

   The eval runner and the gold-section matching will read this file.
8. Exit with a non-zero code if any paper failed.

### Out of scope for this step
- Fixing the page-number fallback (gap #3). Open RAGBench gold labels are by section, not page, so it doesn't affect us yet.
- Configurable chunking. Later experiments will reuse this script with `--project-name` set per ingestion config.
- Batching the per-chunk database round trips.

## Roadmap after this step (each one gets its own plan)
3. **Match gold sections to chunks** (`open_ragbench/gold.py`). *Done 2026-11-10.*
   - A chunk is gold if it contains at least 15% of the gold section's 5-word sequences (normalized, with table/image placeholders removed; the threshold is a setting).
   - 180 of 186 answerable questions match. The 6 unmatched ones (all dev, long maths sections) are left out of the retrieval metrics and reported. They stay in the answer-quality metrics.
   - `--write` saves `data/gold/<project-name>.json`: all 206 questions with `answerable`, `matched` and `gold_chunks` (id, chunk_index, page, coverage). The runner reads this file.
4. **Eval pipeline** (`open_ragbench/pipeline.py`). *Done 2026-11-10.* `src/` is untouched: the file only imports and calls app code.
   - One YAML file per experiment in `open_ragbench/configs/` (the file name is the run name) with `split`, `retrieval_only`, `guardrail` and `settings`. Only query-time settings are accepted. The generator model is the app default.
   - Repeats the app's retrieval steps so it can return the full ranked list and the rerank status. A parity check against `retrieve_context_and_build_prompt` passed.
   - Retrieval metrics: Hit@{1,3,5,10}, MRR, context hit, and paper-level Hit and MRR, overall and by source and type. Results go to `data/results/<name>.json`. `--compare` prints a table of runs.
   - Cohere trial key: rerank calls are limited to 10/min and a 429 is retried. Time spent waiting is kept out of the latency numbers.
5. **Answer-quality run:** the same pipeline with `retrieval_only: false` saves answers and contexts. The settings shortlisted from retrieval-only sweeps on dev get run this way.
6. **Metrics:**
   - **Retrieval, our own code (deterministic):** Hit@{1,3,5,10} and MRR, both by chunk and by paper, against the gold chunk ids. Matched answerable questions only.
   - **Ragas (0.4.3, `ragas.metrics.collections`), for all answer-quality metrics:**
     - `Faithfulness`: claim-level, against the retrieved chunks
     - `AnswerRelevancy`: does the answer address the question
     - `AnswerCorrectness`: against the reference answer (claim overlap plus semantic similarity, which copes with short references like "Yes.")
   - The Ragas judge LLM is a stronger model than the generator. Measure the cost on a trial run first.
   - Each Ragas metric is checked against 10 hand labels, and its agreement is reported.
   - refusal accuracy and false-refusal rate
   - latency, tokens and cost
   - every metric broken down by source and type
7. **Experiments on dev, then baseline and final on test, then the README.**

## Verification
1. **Start services:** `./start_db.sh`, then activate the poetry venv. Redis and Celery aren't needed.
2. **Trial:** `python -m evaluation.open_ragbench.ingest --limit 2`. Expect 2 papers `completed`, and the run file to show the seconds and chunk count for each. Use the timing to estimate the full run before starting it.
3. **Spot-check in the local Supabase studio, or with a short query:**
   - `document_chunks` for those 2 documents has `page_number` set
   - `original_content.text` is non-empty
   - table chunks contain `tables` HTML
4. **Resume:** re-run the same command. Both papers should be skipped. Then set one document's status to `failed` and re-run: it should be deleted and indexed again.
5. **Regression:** upload a file through the UI or the `/file/confirm` path. Celery ingestion should still work, which shows `local_path=None` behaves exactly as before. Create a project in the UI and confirm its settings row matches the old defaults.
6. **Full run:** `python -m evaluation.open_ragbench.ingest`. Expect all 40 papers `completed` and the totals written to the run file.

## Status (2026-11-17): paused until the Cohere monthly reset

**Why paused:** the Cohere trial key hit its limit of 1,000 API calls per month (429: "limited to 1000 API calls / month") partway through Phase D. Every remaining step reranks with Cohere, at least for the unanswerable questions that retrieval-only runs skipped, so nothing more runs until the key resets (or a production key is used).

**Done:**

| Step | Status | Where |
|---|---|---|
| Dataset, ingestion, gold matching, pipeline, Ragas | done (11-09 to 11-16) | sections above |
| A1 prompt size | done | results doc, "A1" |
| A2 Ragas vs hand labels | labels drafted by Claude; **waiting for your review** | `data/labels/no-rerank.json` |
| A3 refusal metrics, A4 cost per query | done; 4 old runs rescored | results doc, "A3", "A4" |
| B1–B3 pool hit, `--paired`, `--compare` upgrades | done | `pipeline.py` |
| C1 retrieval-only sweep (7 configs) | done | results doc, "Phase C" |
| C3 `hybrid-cps20-kw07` | stopped (Cohere throttling), no results | |
| C2 multi-query configs | not run | |
| C4 shortlist | done: baseline, cps20, rerank35-cps20 | results doc, "Phase C" |
| `--reuse-retrieval` (saves Cohere calls in D/E) | built and tested | `pipeline.py` |
| D1 finalists | baseline ran once but the Cohere cap hit; result archived, not used. cps20 and rerank35-cps20 stopped. | results doc, "Phase D (partial)" |

**After the reset, in this order (commands in `evaluation/open_ragbench/run_experiments.sh`):**
1. **D1:** the 3 finalist runs with `--overwrite --reuse-retrieval <same name>`. Cohere: 36 calls. OpenAI: about $0.87 per run, about $2.60 in total (measured on the archived baseline run).
2. **D2:** `--compare` and `--paired` on the finalists, then pick the winner.
3. **E1:** ctx3/ctx8 on the winner, with `--reuse-retrieval <winner>`. Cohere: about 24 calls.
4. **F:** the chunking variant (re-ingest, gold, two runs). Needs a cost estimate first.
5. **G:** the test split, 2 runs of 82 questions. Cohere: about 164 calls.
6. **H:** the README write-up.

Budget: steps 1, 3 and 5 need about 225 Cohere calls. F needs about 124 per run if the variant's runs are live. One month's 1,000 calls covers all of it.

**Before the reset (no Cohere needed):** review the A2 labels.

## Runbook: what to run after the Cohere reset

Run from `server/` with the local DB up (`./start_db.sh`). Run Cohere steps one at a time. **Before each OpenAI run: state the cost and get an OK.**

**0. Before the reset (no Cohere, no cost).** Review the A2 labels with the review sheet, set `reviewed: true` on each item, then re-check the agreement:
```bash
python -m evaluation.open_ragbench.analysis label-sources --run no-rerank     # regenerates data/labels/no-rerank.review.md
python -m evaluation.open_ragbench.analysis label-agreement --run no-rerank
```

**1. D1: finalists with generation + Ragas** (Cohere 36 calls, about $2.60, about 15 min each):
```bash
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/baseline.yaml --overwrite --reuse-retrieval baseline
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/cps20.yaml --overwrite --reuse-retrieval cps20
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/rerank35-cps20.yaml --overwrite --reuse-retrieval rerank35-cps20
```
Check each summary shows `rerank failed 0`.

**2. D2: pick the winner** (free):
```bash
python -m evaluation.open_ragbench.pipeline --compare baseline cps20 rerank35-cps20 --by modality
python -m evaluation.open_ragbench.pipeline --paired baseline cps20
python -m evaluation.open_ragbench.pipeline --paired baseline rerank35-cps20
python -m evaluation.open_ragbench.pipeline --paired cps20 rerank35-cps20
```
Primary: gold in context and MRR. Secondary: AnswerCorrectness deltas, to the extent A2 trusts them, plus false-refusal rate and cost per query. Ties go to the simpler config (baseline < cps20 < rerank35-cps20).

**3. E1: context size on the winner** (Cohere 0 calls: after D1 the winner's file has rankings for all 124 questions; about $1.70):
- Rename `cps20-ctx3.yaml` / `cps20-ctx8.yaml` to `<winner>-ctx3.yaml` / `<winner>-ctx8.yaml` and copy the winner's settings in.
- Run each with `--reuse-retrieval <winner>`. The ranking settings must match the winner's; only `final_context_size` differs.
- Then `--paired <winner> <winner>-ctx3` and `--paired <winner> <winner>-ctx8`.
- Watch cost per query: more chunks bring in more images (A1).

**4. F: one chunking variant** (cost unknown until a 2-paper trial):
- Build the eval-side ingest path (F1), then trial with `--limit 2` to measure the summary-LLM and embedding cost.
- Ask, then do the full ingest into `evals-chunk1500`, then `gold.py --project-name evals-chunk1500 --write`.
- Run the winner on the new project at ctx 5 and ctx 10 (Cohere about 248 calls, since no saved retrieval exists for the new project).

**5. G: test split, once** (Cohere about 164 calls, about $1.20):
- Create `test-baseline.yaml` and `test-final.yaml` (`split: test`, `retrieval_only: false`).
- Run both, then `--paired test-baseline test-final`.
- Report the result whatever it shows. No tuning after this.

**6. H: README write-up.**

**Cohere budget for the month:**

| Step | Calls |
|---|---|
| D1 | 36 |
| E1 | 0 |
| F | about 248 |
| G | about 164 |
| **Total** | **about 450 of 1,000** |

That leaves room for one re-run, or for the optional multi-query configs (C2, about 112 each).

## To-dos, in order of execution (updated 2026-11-17)

**Goal:** a complete, defensible eval to point to in interviews: a baseline, controlled experiments, settings chosen from data on dev, and the winner confirmed once on test. Each step below names the interview question it answers.

**Rules for every step:**
- Before every run that calls OpenAI, state the estimated cost and wait for an OK.
- Never change `src/`. Everything goes in `evaluation/`.
- Run the Cohere rerank configs one at a time (trial key: 10 calls/min).
- Check the Cohere dashboard for the trial key's monthly call cap before the sweep. About 112 calls per rerank run.

### Phase A. Use the results we already have (no new runs, no API cost except where noted)
The three no-rerank runs already contain answers, contexts, tokens and unanswerable questions, so these can start now.

- [x] **A1. Generator prompt size.** *Done 2026-11-17: images are 87% of input tokens; see EVAL_RESULTS_LOG.md.* *"What does it cost per query?"* The generation runs send about 2.71M input tokens for 124 dev questions, about 22k per question, or about 4.4k per chunk with 5 chunks. Find what fills the prompt: table HTML, image content in `original_content`, or something else. This affects the app's cost too, and it decides how meaningful the `ctx3`/`ctx8` runs are.
- [ ] **A2. Check Ragas against hand labels.** *Labels drafted by Claude 2026-11-17; waiting for your review in `data/labels/no-rerank.json`, then re-run `analysis.py label-agreement`.* *"Can you trust your LLM judge?"* AnswerCorrectness is about 0.47 while Faithfulness is about 0.87. Hand-label about 10 answers from an existing run and report how well each Ragas metric agrees with the labels. Find out whether the answers are wrong or whether short references like "Yes." pull the score down. This must be settled before Ragas is used to choose between the finalists.
- [x] **A3. Refusal metrics.** *Done 2026-11-17 (`--rescore` applied to the 4 existing runs).* *"What happens when the answer isn't in the documents?"* Add refusal accuracy (the share of the 12 unanswerable dev questions that are refused) and the false-refusal rate (the share of answerable questions that are refused) to `pipeline.py`. Score the existing no-rerank runs with it.
- [x] **A4. Cost per query.** *Done 2026-11-17; the Ragas judge counter still needs a 3-question paid trial to confirm.* *"What does it cost per query?"* Convert the generator tokens to dollars at gpt-4o-mini prices, and log the Ragas judge's tokens and cost separately. Report cost per query next to latency.

### Phase B. Analysis tooling, built before the sweep so every run is read the same way
- [x] **B1. Gold in the candidate pool.** *Done 2026-11-17.* *"Why did that config win?"* Report whether a gold chunk was among the search candidates before rerank. `search_chunk_ids` is already saved per question. This separates search-recall wins (getting the 13 missed baseline chunks into the pool) from rerank wins.
- [x] **B2. Paired comparison.** *Done 2026-11-17 (`--paired A B`).* *"How do you know the winner is really better?"* For two runs on the same questions, count the questions each one wins and loses (gold in context and H@1). Add a paired bootstrap confidence interval for the difference in MRR. A gap under ~3 points, or a confidence interval that includes 0, counts as a tie.
- [x] **B3. Text-only vs image split in the report.** *Done 2026-11-17 (`--compare all --by modality`).* H@1, H@5, H@10, MRR, gold in context and p50 latency for text-only and image questions. `--compare` doesn't break results down by source yet.

### Phase C. Retrieval-only sweep on dev (no generation, no Ragas)
Commands are in `evaluation/open_ragbench/run_experiments.sh`. All configs have `retrieval_only: true`. *"Did you tune your retrieval?"*

- [x] **C1. Main sweep:** *Done 2026-11-17.* `cps20`, `cps30`, `cps20-thr02`, `cps30-thr02`, `hybrid-cps20`, `hybrid-cps20-kw05`. OpenAI cost: question embeddings only, under $0.001 per run.
- [ ] **C2. Multi-query:** *(not run; optional after the reset)* `mq-vector-cps20`, `mq-hybrid-cps20`. One extra gpt-4o-mini call plus 5 embeddings per question, about $0.02–0.03 per run. Ask before running.
- [ ] **C3. Remaining settings** *(2026-11-17: `rerank35-cps20` done; `hybrid-cps20-kw07` stopped by Cohere throttling, no results; `mq-vector-cps20-nq3` not run.)* (new configs, retrieval-only):
  - `rerank35-cps20`: Cohere `rerank-v3.5` on the cps20 pool. Was dropped earlier, now back in.
  - `hybrid-cps20-kw07`: keyword-heavy hybrid search (vector 0.3, keyword 0.7).
  - `mq-vector-cps20-nq3`: 3 query variants instead of 5. Cheaper; checks whether 5 are needed.
  - If hybrid or multi-query wins C1/C2, a cps30 version of the winner.
- [x] **C4. Report and decide.** *Done 2026-11-17: shortlist is baseline, cps20, rerank35-cps20 (EVAL_RESULTS_LOG.md, Phase C).* Put every run next to the existing `baseline` row, using B1 to B3. Treat ties as ties and pick the simpler, cheaper, faster config.

### Phase D. Finalists: generation + Ragas on dev
- [ ] **D1. Shortlist** *(2026-11-17: shortlist chosen in C4; runs paused at the Cohere cap, see Status)* the top 2 configs plus the rerank baseline. Set `retrieval_only: false` and run them with `--overwrite` (the baseline too, since its file is retrieval-only). Report Ragas scores, refusal metrics (A3), cost per query (A4) and latency. Estimated cost: about $0.42 per run for generation plus the Ragas judge, which A4 measures. Ask before running.
- [ ] **D2. Pick the winner** using the paired comparison (B2) on gold in context and AnswerCorrectness, taking the A2 hand-label check into account.

### Phase E. Context size on the winner only
- [ ] **E1.** Point `cps20-ctx3.yaml` and `cps20-ctx8.yaml` at the winner's settings, then run them with generation and Ragas. *"How many chunks do you give the model, and why?"* Use the A1 finding to explain the trade-off between tokens and quality. `ctx10` was dropped: only 2 of 106 baseline questions could gain from more than 5 chunks.

### Phase F. One chunking variant
*"Did you tune chunk size?"* Chunking is hard-coded in `src/rag/ingestion/chunking.py` (`chunk_by_title`, max 3000 / new after 2400 / combine under 500 characters), and `src/` stays untouched. So:

- [ ] **F1.** Write an eval-side ingest path that copies the ingestion steps with different chunk sizes (for example max 1500 / new after 1200). It indexes into a new project, such as `evals-chunk1500`, using `ingest.py --project-name`.
- [ ] **F2.** Re-run `gold.py --write` for the new project, because the chunk ids change.
- [ ] **F3.** Run the winning config on both projects and compare them with B1 and B2.

Cost: re-ingesting 40 papers repeats the summary-LLM calls and embeddings for every chunk, and took about 140 s per paper. Estimate the cost on a 2-paper trial and ask before the full run.

### Phase G. Confirm on test, once
- [ ] **G1.** Run the final config and the baseline on the **test** split (74 answerable + 8 unanswerable questions) with generation and Ragas. *"Did you overfit to your dev set?"* Report the numbers whether or not they hold up. Don't tune after this. Estimated cost: about the same as a dev finalist run. Ask before running.

### Phase H. Write-up
- [ ] **H1.** A README section covering the dataset, the method (baseline, controls, one change at a time, retrieval-first funnel, the noise threshold and paired tests), the results tables, the chosen settings and the reasons for them, and the failure analysis (search recall, image questions).
- [ ] **H2.** State the scope precisely: 106 scorable dev questions over 40 arXiv papers; query-time settings plus one chunking variant tuned; winner confirmed on test; gpt-4o-mini as both generator and judge.
