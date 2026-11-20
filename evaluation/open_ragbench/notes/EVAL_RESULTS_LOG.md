# Open RAGBench eval: baseline results and next runs

> Working notes kept during the eval: the plan, cost approvals and the run order. The write-up for readers is [documentation/EVALUATION.md](../../../documentation/EVALUATION.md).

Run: `baseline` (2026-11-10). Results file: `evaluation/open_ragbench/data/results/baseline.json`.
Config: `evaluation/open_ragbench/configs/baseline.yaml`.

## What was run

- **Questions:** the 112 **dev** questions, each through the app's own retrieval with its default settings:
  - vector search returns the **10** chunks most similar to the question (`chunks_per_search: 10`, `similarity_threshold: 0.3`)
  - Cohere `rerank-english-v3.0` reranks those 10
  - the top **5** go to the generator (`final_context_size: 5`)
- **Retrieval only:** no answers were generated.
- **Scored:** 106 questions. The other 6 are left out because their gold section didn't match any chunk. They're long maths sections spread over many chunks.
- **Rerank:** 0 failures and 1 rate-limit retry. Every question was reranked.

## What each metric means

Every question has one or more **gold chunks**, the chunks that contain the section the answer comes from (from `gold.py`).

- **H@k (Hit@k):** the share of questions whose gold chunk appears in the top _k_ of the ranked list. H@1 = 0.708 means the very first chunk was the right one for 71% of questions.
- **MRR (mean reciprocal rank):** for each question, take 1 divided by the position of the first gold chunk (1st → 1, 2nd → 0.5, 3rd → 0.33, missing → 0), then average. It rewards ranking the gold chunk high, not just finding it.
- **Gold in context (ctxHit):** whether a gold chunk is among the chunks the generator actually sees. This matters most for answer quality, because the model can only use what it's given. With the default 5-chunk cut it's the same as H@5.
- **Paper H@1 / Paper MRR:** the same as H@1 and MRR, except any chunk from the right paper counts. They separate finding the right paper from finding the right chunk.

## The numbers

|                  | n   | H@1   | H@3   | H@5   | H@10  | MRR   | Gold in context | Paper H@1 |
| ---------------- | --- | ----- | ----- | ----- | ----- | ----- | --------------- | --------- |
| **overall**      | 106 | 0.708 | 0.821 | 0.859 | 0.877 | 0.768 | 0.859           | 0.981     |
| text             | 61  | 0.869 | 0.902 | 0.918 | 0.934 | 0.888 | 0.918           | 0.967     |
| text-image       | 24  | 0.375 | 0.583 | 0.625 | 0.667 | 0.472 | 0.625           | 1.000     |
| text-table       | 8   | 0.500 | 0.750 | 0.875 | 0.875 | 0.650 | 0.875           | 1.000     |
| text-table-image | 13  | 0.692 | 0.923 | 1.000 | 1.000 | 0.823 | 1.000           | 1.000     |
| abstractive      | 64  | 0.656 | 0.797 | 0.859 | 0.859 | 0.731 | 0.859           | 1.000     |
| extractive       | 42  | 0.786 | 0.857 | 0.857 | 0.905 | 0.824 | 0.857           | 0.952     |

Latency, excluding the rate-limit waits, which only exist in the eval:

| Stage           | p50    | p95    |
| --------------- | ------ | ------ |
| Search          | 0.58 s | 1.07 s |
| Rerank          | 0.71 s | 2.92 s |
| Retrieval total | 1.37 s | 4.19 s |

## What it tells us

**1. Finding the right paper is nearly solved; finding the right chunk is the real problem.**
Paper H@1 is 0.98: the top chunk comes from the correct paper for 104 of 106 questions. Chunk H@1 is 0.71, so about 30% of the time the system is in the right paper but at the wrong place in it. The corpus has 40 papers on mostly different topics, so telling papers apart is easy. Telling sections of the same paper apart is hard.

**2. For 86% of questions, the generator gets the right evidence.**
Gold in context is 0.859, so for 91 of 106 questions the right chunk is in the 5 chunks given to the model. For the other 15, the model can't answer correctly from evidence. It will either refuse or answer from loosely related chunks, and the second case is where hallucinations come from. 0.859 is roughly the ceiling for answer correctness with these settings.

**3. Where those 15 failures happen:**

- **13 are search misses.** The gold chunk wasn't among the 10 candidates at all, although the right paper was found in every case. The rerank can only reorder what search gives it, so it can't fix these. H@10 = 0.877 is the ceiling for these settings.
- **2 were found at ranks 6–10** and then dropped by the 5-chunk cut. So a bigger `final_context_size` would gain at most 2 questions.

So the lever is **search recall** (more candidates, or a different search), not the cut or the reranker.

**4. Image questions are clearly the weak spot.**

- text-image questions have an H@1 of 0.375, against 0.869 for text.
- 8 of the 13 search misses are image questions.

The likely cause is how images end up in chunks. The question asks about what a figure shows, such as how two distortions compare in a scatterplot. The chunk holds the figure's caption plus noisy OCR text from the plot axes, and the summary that gets embedded may not describe what the figure shows. So the question embedding and the chunk embedding don't line up well. The right paper is still found every time (Paper H@1 1.000), just not the right chunk.

**5. Text-table-image questions do surprisingly well** (H@5 = 1.000). These sections are long and contain a lot of prose, so there's plenty of text to match. With only 13 questions (and 8 for text-table), a single question moves the score by 8–12 points, so treat the small groups as rough indications.

**6. Extractive questions are easier than abstractive ones** (MRR 0.824 vs 0.731). Extractive questions reuse the paper's own wording, which embeddings match well. Abstractive questions paraphrase it.

**7. Rerank helps a lot.** A first, invalid run, where 92 of 112 reranks had failed on the Cohere trial-key rate limit and fallen back to search order, scored about H@1 0.52. With rerank working it's 0.71. The `no-rerank` config will measure this properly.

## Things to keep in mind

- **Small sample:** 106 questions means each one is worth about 1 point overall, so differences under about 3 points between configs are probably noise.
- **Dev only:** pick settings on dev, then confirm the winner once on test.
- **Retrieval only:** this says nothing yet about answer quality. That comes from the generation runs (`retrieval_only: false`) and Ragas for the shortlisted settings.
- **Comparing Hit@k:** only compare it for k ≤ the smallest `chunks_per_search` of the runs being compared. All the configs below use at least 10, so H@1 to H@10 are comparable.

## Next runs: the sweep configs

> **Superseded (2026-11-17):** this was the original sweep plan. The sweep that actually ran is retrieval-only, `rerank35-cps20` was later added back, and the results are in "Phase C: retrieval-only sweep" at the end of this file.

All of these are in `evaluation/open_ragbench/configs/`, retrieval-only, on dev. Each file has a comment explaining the reasoning. They target point 3: getting the 13 missed chunks into the candidate pool.

| Config              | What changes                                            | What it tests                                                                                                              |
| ------------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `no-rerank`         | rerank off                                              | Control: how much rerank adds. Not throttled, so it takes about 1 min.                                                     |
| `cps20`             | 20 search candidates                                    | Does a bigger candidate pool recover the missed chunks?                                                                    |
| `cps30`             | 30 candidates                                           | Does recall keep rising, or does the rerank get noisier?                                                                   |
| `cps30-thr02`       | 30 candidates, threshold 0.2                            | Lets the pool actually fill up. The 0.3 threshold already cut 3 baseline searches short (9, 9 and 1 results).              |
| `hybrid-cps20`      | hybrid search (vector 0.7 / keyword 0.3), 20 candidates | Can keyword search find exact terms that the embeddings miss?                                                              |
| `hybrid-cps20-kw05` | hybrid search with equal weights (0.5 / 0.5)            | Should keyword search count more?                                                                                          |
| `mq-vector-cps20`   | 5 query variations, 20 candidates                       | Aimed at image and abstractive questions, whose wording differs from the chunk text. Adds 1 gpt-4o-mini call per question. |
| `rerank35-cps20`    | Cohere `rerank-v3.5`, 20 candidates                     | Newer reranker on the same pool as `cps20`.                                                                                |

I didn't include a larger `final_context_size`: only 2 of 106 questions could gain from it.

### Commands

Run from `server/`. Start the local database first with `./start_db.sh`.

**Run configs one at a time.** The Cohere trial key allows 10 calls per minute, and the rate limiter only works within one process. Two rerank runs side by side would both hit the limit. Each rerank-on run takes about 12 minutes; `no-rerank` takes about 1 minute. All 8 take about 85 minutes.

Run one config:

```bash
poetry run python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/cps20.yaml
```

Run the whole sweep, one after another:

```bash
for c in no-rerank cps20 cps30 cps30-thr02 hybrid-cps20 hybrid-cps20-kw05 mq-vector-cps20 rerank35-cps20; do
  poetry run python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/$c.yaml
done
```

Compare all runs (one row per run, sorted by MRR):

```bash
poetry run python -m evaluation.open_ragbench.pipeline --compare baseline no-rerank cps20 cps30 cps30-thr02 hybrid-cps20 hybrid-cps20-kw05 mq-vector-cps20 rerank35-cps20
```

Other useful options:

- Quick trial on the first N questions (saved as `<name>-limitN`): `--limit 10`
- Re-run a config whose results file already exists: `--overwrite`
- Inspect one question in detail with a config's settings:
  ```bash
  poetry run python -m evaluation.open_ragbench.pipeline --question-id <ID> --config evaluation/open_ragbench/configs/cps20.yaml --retrieval-only
  ```
- Make a new experiment: copy `configs/baseline.yaml` to `configs/<new-name>.yaml` and change the `settings` block. The file name becomes the run name.

### What to look for in the comparison

1. **H@10 and Gold in context** going above 0.877 and 0.859 means the bigger pool or the other search recovered missed chunks.
2. **text-image rows**: whether any config improves the weak spot (H@1 0.375).
3. **H@1 and MRR**: whether the rerank keeps the gold chunk on top with a bigger, noisier pool.
4. **Latency**: hybrid and multi-query add search time. Multi-query also adds an LLM call.
5. **Warnings**: any run with rerank failures or errors isn't valid. Re-run it with `--overwrite`.

Then take the best 2–3 configs, copy them with `retrieval_only: false`, and run them to generate answers for the Ragas step.

## Findings: Phase A

### A1. Images make up 87% of the generator's input tokens (2026-11-17)

Run: `no-rerank` (dev, 124 generated questions). Command:
```bash
poetry run python -m evaluation.open_ragbench.analysis prompt-size --run no-rerank
```

**What the "22k tokens per question" really is.** The median question uses **3,068** input tokens. The mean is 21,875 because **22 of 124 questions** have images in their final 5 chunks, and those 22 use **90%** of all input tokens. The largest single prompt is 400k tokens: 32 images from 5 chunks.

**Why.**
- `prepare_prompt_and_invoke_llm` attaches every base64 image of the final chunks at default (high) detail.
- gpt-4o-mini bills an image as 2,833 tokens plus 5,667 per 512-px tile. That is about 33× gpt-4o's token count, so the dollar cost per image is about the same as gpt-4o's.
- A tiny sliver (for example 160×32 or 1×548, from equations or plot fragments that `hi_res` partitioning cut out) still costs 8.5k–14k tokens.

**The estimate checks out.** Text tokens (tiktoken) plus a fixed 207-token prompt overhead plus the image formula match the observed counts with a **median error of 0.1%** (max 0.6%) on the 22 image questions. Images account for **2.36M of 2.71M tokens (87%)**: $0.35 of the run's $0.41 input cost.

**What the fixes would save** (same 153 images; all are app changes, so these are recommendations only):

| Option | Input tokens per run | vs now | Input cost per run |
|---|---|---|---|
| Now (high detail, every image) | 2.71M | 100% | $0.41 |
| Drop images with a short side under 100 px (59 of 153) | 2.17M | 80% | $0.33 |
| Send every image at `detail: "low"` | 0.79M | 29% | $0.12 |
| Both | 0.62M | 23% | $0.09 |

**What it means for the eval.**
- **Cost:** per-query cost is very uneven. Most questions cost about $0.0005; a few cost up to $0.06. So report cost per query as both median and mean (A4).
- **Context size:** `final_context_size` mostly changes cost through the images that larger chunk sets bring in. Watch this in the ctx3/ctx8 runs (Phase E).
- **Faithfulness:** the Ragas judge sees texts and tables but not images. An answer that uses an image correctly can look unsupported.

### A2. Ragas vs hand labels (PRELIMINARY: labels drafted by Claude, not yet reviewed)

Sample: 20 answered dev questions from `no-rerank`, stratified by AnswerCorrectness quartile, 5 of them refusals. Labels are in `evaluation/open_ragbench/data/labels/no-rerank.json` (`draft_by: claude`, `reviewed: false`). Command:
```bash
poetry run python -m evaluation.open_ragbench.analysis label-agreement --run no-rerank
```

| Ragas metric | Questions | Spearman vs label | Agreement at 0.5 |
|---|---|---|---|
| AnswerCorrectness | all 20 | +0.75 | 55% |
| AnswerCorrectness | 15 non-refused | +0.31 | 40% |
| Faithfulness | all 20 | 0.00 | 75% |
| Faithfulness | 15 non-refused | +0.32 | 87% |
| AnswerRelevancy | all 20 | +0.76 | 100% |

**What it shows (pending review):**
- **AnswerCorrectness compresses correct answers to about 0.3–0.6.** The 12 answers labelled fully correct average **0.51** (minimum 0.31). So the run-level 0.47–0.51 does **not** mean "half the answers are wrong". Its high correlation over all 20 comes mostly from separating refusals; among real answers it ranks only weakly (+0.31). Length explains little (Spearman −0.14 with answer words), so it isn't simple verbosity. Verdict: **trust with caveat.** Use it only as paired deltas between configs, never as an absolute score or with a 0.5 threshold, and never as the primary selector.
- **Faithfulness works on real answers (87% agreement) but scores refusals 0.** A refusal makes no claims, so 0 is wrong. Verdict: **trust, with refusals excluded** (done in A3).
- **AnswerRelevancy agrees on every item,** but it mostly separates answers from refusals. Verdict: **trust, low information.**
- **Faithfulness misses images.** One answer drew on a figure (item 17, "best-effort data"), but the judge only sees texts and tables (see A1).

### A3. Refusals (`no-rerank`, dev)

- **Refusal accuracy is 0.917** (11 of 12 unanswerable questions refused). **The false-refusal rate is 0.080** (9 of 112 answerable).
- **8 of the 9 false refusals are retrieval misses:** the gold chunk wasn't in the context. Only 1 is a generator failure, the torsor question, where the answer was in the first chunk.
- Image questions are refused falsely more often (0.128 vs 0.055 for text-only).
- **The Ragas means now leave refusals out.** On `no-rerank`, AnswerCorrectness becomes 0.506 and Faithfulness 0.915, over 103 answers.
- All four existing runs were rescored (`--rescore`) with no API calls; their retrieval metrics are unchanged.

### A4. Cost per query

- **`no-rerank` (generation, no rerank):** p50 **$0.00056**, mean **$0.00339**, max **$0.060**. The mean is 6× the median because of image-heavy prompts (A1).
- **Rerank:** at Cohere's list price ($2 per 1k searches) it adds **$0.002 per query**. That is 3.5× a typical text-only answer. The trial key is free, but this matters for a production cost story.
- **Ragas judge cost** is now logged per run (`ragas.tokens`, `ragas.cost_usd`). It wasn't recorded for the existing runs and will be checked on a 3-question trial.

### B. Analysis tooling, with a first result
- `--compare` now has: pool hit, deltas vs the baseline, `--by modality`, `all`, retrieval p50 (comparable across runs) and cost per query.
- `--paired A B` gives wins and losses, an exact McNemar p-value, a bootstrap 95% CI and a verdict. Sanity checks:
  - a run against itself: all ties
  - `no-rerank` → `baseline`: H@1 **+26.4 pts** [+17.9, +35.8], 30 wins vs 2 losses, p < 0.001
- **First result: a bigger pool does help recall.** `cps20-no-rerank` has gold in the candidate pool for **92.4%** of questions vs 87.7% at 10 candidates (+4.7 pts, 5 wins, 0 losses). Image questions gain the most: 0.784 → 0.892. Without rerank those chunks stay below the top 5, so `cps20` **with** rerank is the run to watch in Phase C.

## Phase C: retrieval-only sweep (dev, 2026-11-17)

**What ran:** 7 rerank configs, retrieval-only, on 106 scorable dev questions. All are valid: 0 errors, 0 rerank failures.
- `hybrid-cps20-kw07` was stopped partway: Cohere slowed to about 1 question per minute, probably rate limiting on the trial key. It has no results.
- The 3 multi-query configs weren't run (not approved).

Commands:
```bash
poetry run python -m evaluation.open_ragbench.pipeline --compare baseline cps20 cps30 cps20-thr02 cps30-thr02 rerank35-cps20 hybrid-cps20 hybrid-cps20-kw05 --by modality
poetry run python -m evaluation.open_ragbench.pipeline --paired baseline cps20   # and so on per config
```

| Config | H@1 | H@5 | MRR | Gold in context | Pool hit | Context hit, text-only (69) | Context hit, with-image (37) |
|---|---|---|---|---|---|---|---|
| baseline (10 candidates, rerank v3.0) | 0.708 | 0.859 | 0.768 | 0.859 | 0.877 | 0.913 | 0.757 |
| cps20 | 0.726 | 0.877 | 0.797 | 0.877 | 0.924 | 0.899 | 0.838 |
| cps20-thr02 | *identical to cps20* | | | | | | |
| cps30 | 0.726 | 0.887 | 0.802 | 0.887 | 0.943 | 0.899 | 0.865 |
| cps30-thr02 | 0.726 | 0.887 | 0.803 | 0.887 | **0.953** | 0.899 | 0.865 |
| rerank35-cps20 | **0.736** | **0.896** | 0.801 | **0.896** | 0.924 | 0.927 | 0.838 |
| hybrid-cps20 | 0.726 | 0.868 | 0.797 | 0.868 | 0.924 | 0.899 | 0.811 |
| hybrid-cps20-kw05 | *identical to hybrid-cps20* | | | | | | |

**Paired tests vs the baseline (`--paired`):**
- **No config beats the baseline on what the generator sees.** For gold in context, every gap is +0.9 to +3.8 points with a 95% CI that includes 0. The best is rerank35-cps20 (+3.8, 5 wins vs 1 loss, p = 0.22).
- **MRR and H@1 are ties for every config.**
- **The only significant gain is the candidate pool:**
  - cps30: +6.6 pts, 7 wins vs 0 losses, p = 0.016
  - cps30-thr02: +7.5 pts, 8 vs 0, p = 0.008
  - cps20: +4.7 pts, p = 0.06
- **Against cps20:** cps30, rerank-v3.5 and hybrid are all ties on every metric.

**What it means:**
1. **More candidates fix search recall, but rerank doesn't turn that into context.** The pool recovers 5–8 of the baseline's 13 search misses. Only 2–3 of them reach the top 5, and the gain is partly offset by a few text-only questions that drop out of the top 5 (text-only context hit −1.4 pts).
2. **The gains are all in image questions.** With-image context hit rises from 0.757 to 0.838–0.865 (+8 to +11 pts). Text-only questions stay flat. With 37 image questions this is directional, not proven, but it fits the earlier diagnosis that image chunks are the weak spot.
3. **Hybrid search adds nothing.** Keyword search finds no gold chunk that vector search misses (identical pool at 20 candidates), and the 0.7/0.3 and 0.5/0.5 weights give identical results.
4. **The 0.2 similarity threshold does nothing at 20 candidates** and adds one pool hit at 30. It never decides what reaches the generator.
5. **Rerank v3.5 vs v3.0 on the same pool is a tie** (+1.9 pts gold in context, 2 wins vs 0 losses).
6. **Cost and latency:** at list price every config costs the same per query (one rerank search; even 30 candidates fit in one Cohere search). Rerank latency roughly doubles with 20–30 candidates (p50 retrieval about 2.3–2.8 s vs 1.4 s), but Cohere trial-key latency is noisy: kw05 measured 1.4 s on the same pool. So treat latency as indicative only.

**Shortlist for Phase D (generation + Ragas):**
- **baseline:** required. Under the tie rule it is also the default winner (simplest, fastest).
- **cps20:** the simplest change. It ties cps30 everywhere, with a smaller pool and lower rerank latency.
- **rerank35-cps20:** the highest gold in context and the largest image-question gain, and a different lever (the reranker rather than the pool).

Dropped:
- cps30 and cps30-thr02: they tie cps20 on everything the generator sees, and their extra pool recall doesn't reach the context.
- the threshold variants: no effect.
- hybrid: no effect.

## Phase D (partial): finalists with generation + Ragas (2026-11-17)

**What happened:** the 3 finalists (baseline, cps20, rerank35-cps20) were started with `--reuse-retrieval`, which takes the ranked lists from the retrieval-only runs. Only the 12 unanswerable dev questions had to call Cohere. During the baseline run the trial key hit its **monthly cap of 1,000 calls**, so all 12 of those reranks failed and fell back to search order. The cps20 and rerank35-cps20 runs were stopped.
- The capped baseline run is archived at `evaluation/open_ragbench/data/results_archive/baseline-generation-cohere-capped.json`. It isn't used for decisions.
- `results/baseline.json` is back to the retrieval-only run, so it can be reused after the reset.

**Indicative numbers from the archived baseline run** (answerable questions had proper reranked context; unanswerable questions had un-reranked context):

| Metric | baseline (rerank) | no-rerank, for reference |
|---|---|---|
| AnswerCorrectness (non-refused) | 0.499 | 0.506 |
| Faithfulness | 0.916 | 0.915 |
| AnswerRelevancy | 0.910 | 0.916 |
| Refusal accuracy (unanswerable) | 0.917 | 0.917 |
| False-refusal rate (answerable) | **0.036** | 0.080 |
| Cost per query, p50 / mean | $0.0026 / $0.0064 | $0.0006 / $0.0034 |

- **Rerank halves the false refusals** (0.080 → 0.036): more questions get their evidence in context, so fewer are refused. This is consistent with gold in context rising from 0.764 to 0.859.
- **AnswerCorrectness doesn't move,** even though gold in context rises by 9.4 points. That fits A2: the metric is compressed and doesn't separate correct answers well.
- **Measured run cost:** generation $0.57 + Ragas judge $0.30 = **$0.87 per finalist run**. The judge-cost counter works. Generation cost more than without rerank because reranked contexts bring in more image-heavy chunks (A1).

**Next, after the Cohere reset:** rerun the 3 finalists (commands in `run_experiments.sh`), then D2.
