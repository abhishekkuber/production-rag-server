# Evaluation

How well does KnowledgeDock find the right evidence and answer from it? This page covers the benchmark, how it is scored, what the numbers show, and what is still to run.

**Status (November 2026):** the retrieval experiments are finished. The generation runs that pick the final settings are paused because the free Cohere API key used for reranking hit its monthly limit of 1,000 calls. [Next steps](#next-steps) lists what runs once the key resets.

## Summary

| Finding | Number |
|---|---|
| The top chunk comes from the right paper | 98% of questions |
| The top chunk is the right section of that paper | 71% |
| The right chunk is among the 5 the model sees | 86% |
| Effect of the Cohere reranker on Hit@1 | +26 points (44% → 71%), significant |
| Effect of hybrid (keyword + vector) search | none on this corpus |
| Image questions vs text-only questions, right chunk in context | 76% vs 91% |
| Share of the generator's input tokens that are images | 87% |

In short: finding the right document is solved, and finding the right part of it is the hard part. The reranker does most of the work, and questions about figures are the weak spot. The cost of an answer depends mostly on how many images end up in the prompt.

## The benchmark

**Dataset.** [Open RAGBench](https://huggingface.co/datasets/vectara/open_ragbench) (Vectara, CC BY-NC 4.0): questions written about arXiv papers, each labelled with the section of the paper that answers it. Many questions are about tables and figures, which tests the multimodal part of the ingestion pipeline. I first planned to use FinanceBench, but indexing its 10-K filings with `hi_res` parsing and LLM summaries cost too much for a side project.

**Subset.** A seeded sample (seed 42), so the same command gives the same set:

| | Papers | Indexed? | Questions |
|---|---|---|---|
| Gold papers | 20 | yes | 186 answerable |
| Distractor papers | 20 | yes | none: they only make retrieval harder |
| Held-out papers | 5 | no | 20 unanswerable: the right response is a refusal |

The 40 indexed papers produce 1,476 chunks (127 with a table, 269 with an image).

**Dev and test split.** 60% of questions are dev (112 answerable + 12 unanswerable) and 40% are test (74 + 8). All tuning happens on dev. Test is run once at the end, on the baseline and the chosen settings, and reported whatever it shows.

**Question types.** By source: text only, text + image, text + table, text + table + image. By style: extractive (reuses the paper's wording) and abstractive (paraphrases it). Every metric is also reported for each type.

**Same code as the app.** The papers were indexed through the app's own ingestion pipeline (`process_document`, reading the PDFs from disk instead of S3). Retrieval uses the app's search and rerank functions, and a parity check confirmed the eval returns the same chunks as the app. Each experiment is a YAML file that overrides only query-time settings. The app's code is unchanged.

## How it is scored

### Retrieval

Open RAGBench labels the answer by section, but the app retrieves chunks. So `gold.py` marks a chunk as gold for a question when it contains at least 15% of the gold section's 5-word sequences (after normalising text and removing table and image placeholders). 180 of 186 answerable questions match at least one chunk. The 6 that don't are long maths sections that the PDF parser broke up; they are left out of the retrieval metrics and reported.

| Metric | Meaning |
|---|---|
| **Hit@k** | Share of questions with a gold chunk in the top k results. Hit@1 = the first chunk is right. |
| **MRR** | Mean of 1 / (rank of the first gold chunk). Rewards ranking the right chunk high, not just finding it. |
| **Gold in context** | A gold chunk is among the chunks the generator actually receives (5 by default). The model can't answer from evidence it never sees, so this is the closest retrieval number to answer quality. |
| **Pool hit** | A gold chunk is among the search candidates before reranking. Separates search failures from rerank failures. |
| **Paper Hit@1** | Like Hit@1, but any chunk from the right paper counts. |

### Answers

- **Refusals.** Refusal accuracy is the share of unanswerable questions the app refuses. The false-refusal rate is the share of answerable questions it refuses.
- **Ragas 0.4.3**, with `gpt-4o-mini` as the judge:
  - Faithfulness: are the answer's claims supported by the retrieved chunks?
  - AnswerRelevancy: does the answer address the question?
  - AnswerCorrectness: does it match the reference answer?

  Refused answers are left out of the Ragas means, so a config can't score better by refusing more.
- **Cost and latency per query**, with the median and the mean reported separately, because a few image-heavy prompts cost 100 times more than a typical one.

The eval calls the app's answer function (`prepare_prompt_and_invoke_llm`, `gpt-4o-mini`) directly. It skips the agent layer and the input guardrail, so the score reflects retrieval and generation only.

### Method

- **One change at a time** from a fixed baseline (the app's default settings).
- **Retrieval first.** Every config is first run without generation, which costs under $0.001 in embeddings. Only a shortlist gets generation and Ragas.
- **Paired tests.** Two configs are compared on the same questions: wins and losses per question, an exact McNemar test, and a bootstrap 95% confidence interval. With 106 scored questions, one question is about 1 point, so a gap under 3 points or a confidence interval that includes 0 counts as a tie. Ties go to the simpler, cheaper config.

## Results

All numbers are on the 106 scorable dev questions.

### Baseline

Default settings: vector search returns the 10 chunks most similar to the question (similarity threshold 0.3), Cohere `rerank-english-v3.0` reorders them, and the top 5 go to the model.

|  | n | Hit@1 | Hit@5 | Hit@10 | MRR | Gold in context | Paper Hit@1 |
|---|---|---|---|---|---|---|---|
| **All** | 106 | 0.708 | 0.859 | 0.877 | 0.768 | 0.859 | 0.981 |
| Text | 61 | 0.869 | 0.918 | 0.934 | 0.888 | 0.918 | 0.967 |
| Text + image | 24 | 0.375 | 0.625 | 0.667 | 0.472 | 0.625 | 1.000 |
| Text + table | 8 | 0.500 | 0.875 | 0.875 | 0.650 | 0.875 | 1.000 |
| Text + table + image | 13 | 0.692 | 1.000 | 1.000 | 0.823 | 1.000 | 1.000 |
| Extractive | 42 | 0.786 | 0.857 | 0.905 | 0.824 | 0.857 | 0.952 |
| Abstractive | 64 | 0.656 | 0.859 | 0.859 | 0.731 | 0.859 | 1.000 |

Median retrieval latency is 1.4 s (0.6 s search + 0.7 s rerank).

What it shows:

- **Right paper, wrong section.** The top chunk comes from the right paper for 104 of 106 questions, but is the right chunk for only 75. The 40 papers cover different topics, so telling papers apart is easy. Telling apart sections of the same paper is hard.
- **The ceiling is search recall.** 15 questions don't get the gold chunk into the model's context. 13 of them failed at search: the gold chunk was never among the 10 candidates, so no reranker could fix it. Only 2 were found and then dropped by the 5-chunk cut, so sending more chunks to the model would help little.
- **Figures are the weak spot.** Text + image questions reach Hit@1 0.375, against 0.869 for text. 8 of the 13 search misses are image questions. The likely cause is in ingestion: a figure's chunk holds the caption, OCR noise from the plot axes and an LLM-written summary, and that summary often doesn't describe what the figure shows, which is what the question asks about.
- Text + table + image questions do well because their sections are long and full of prose to match. The table and mixed groups are small (8 and 13 questions), so treat their numbers as rough.

### The reranker

Same 10 candidates, with and without Cohere rerank:

| | Hit@1 | Hit@5 | MRR | Gold in context | Retrieval p50 |
|---|---|---|---|---|---|
| No rerank | 0.443 | 0.764 | 0.577 | 0.764 | 0.4 s |
| Rerank (baseline) | **0.708** | **0.859** | **0.768** | **0.859** | 1.4 s |
| Change | +26.4 pts | +9.4 pts | +19.1 pts | +9.4 pts | +1.0 s |

Hit@1 went up on 30 questions and down on 2 (McNemar p < 0.001, 95% CI +17.9 to +35.8). It is the largest single effect in the eval. At Cohere's list price ($2 per 1,000 searches) it adds about $0.002 per query, which is more than a typical text-only answer costs to generate.

### Retrieval sweep

Seven configs, each one change from the baseline (retrieval only, no failed reranks):

| Config | What changed | Hit@1 | MRR | Gold in context | Pool hit | Context: text-only (69) | Context: with image (37) |
|---|---|---|---|---|---|---|---|
| baseline | | 0.708 | 0.768 | 0.859 | 0.877 | 0.913 | 0.757 |
| cps20 | 20 search candidates | 0.726 | 0.797 | 0.877 | 0.924 | 0.899 | 0.838 |
| cps20-thr02 | 20 candidates, threshold 0.2 | same as cps20 | | | | | |
| cps30 | 30 candidates | 0.726 | 0.802 | 0.887 | 0.943 | 0.899 | 0.865 |
| cps30-thr02 | 30 candidates, threshold 0.2 | 0.726 | 0.803 | 0.887 | **0.953** | 0.899 | 0.865 |
| rerank35-cps20 | Cohere `rerank-v3.5`, 20 candidates | **0.736** | 0.801 | **0.896** | 0.924 | 0.927 | 0.838 |
| hybrid-cps20 | vector 0.7 + keyword 0.3, 20 candidates | 0.726 | 0.797 | 0.868 | 0.924 | 0.899 | 0.811 |
| hybrid-cps20-kw05 | vector 0.5 + keyword 0.5 | same as hybrid-cps20 | | | | | |

("Context: text-only" and "Context: with image" are gold in context for those two groups of questions.)

What it shows:

- **More candidates fix search recall.** With 30 candidates and threshold 0.2, the gold chunk is in the pool for 95.3% of questions, up from 87.7% (8 wins, 0 losses, p = 0.008). This is the only significant gain in the sweep.
- **But little of that reaches the model.** Gold in context rises 1 to 4 points, and every one of those gains is a statistical tie. The reranker pulls only 2 or 3 of the recovered chunks into the top 5, and a few text-only questions drop out.
- **The gains are on image questions.** Gold in context for questions with images rises from 0.757 to 0.838–0.865. Text-only questions stay flat. With 37 image questions this is a direction, not a proven result, but it matches the diagnosis above.
- **Hybrid search adds nothing here.** Keyword search found no gold chunk that vector search missed, and the two weightings gave identical results. The questions are paraphrased prose, not exact codes or names, which is where keyword search usually helps.
- **The similarity threshold almost never matters.** Lowering it from 0.3 to 0.2 changes nothing at 20 candidates and adds one pool hit at 30.
- **Rerank v3.5 vs v3.0 is a tie** (+1.9 points gold in context on the same pool, 2 wins and 0 losses).

**Shortlist for the generation runs:** the baseline, `cps20` (the simplest change), and `rerank35-cps20` (highest gold in context, and a different lever).

### Answers (preliminary)

A full generation run without rerank (`no-rerank`, 124 dev questions):

| Metric | Value |
|---|---|
| Refusal accuracy (unanswerable questions) | 0.917 (11 of 12) |
| False-refusal rate (answerable questions) | 0.080 (9 of 112) |
| Faithfulness | 0.915 |
| AnswerRelevancy | 0.916 |
| AnswerCorrectness | 0.506 |
| Generation cost per query, median / mean | $0.00056 / $0.0034 |

- **False refusals are mostly retrieval failures.** In 8 of the 9 false refusals, the gold chunk wasn't in the context. The model correctly said it didn't have the information. Only one was a generator mistake.
- **Rerank halves false refusals.** A baseline run with rerank (stopped when the Cohere key ran out, so only partly valid) had a false-refusal rate of 0.036 against 0.080 without rerank. More questions get their evidence, so fewer are refused.
- **AnswerCorrectness looks low, but that number isn't reliable.** See the next section.

### Can the Ragas judge be trusted? (preliminary)

I compared each Ragas metric with hand labels on 20 answers, sampled across the AnswerCorrectness range and including 5 refusals. The labels were drafted with an LLM's help and are still being reviewed by hand, so these numbers may change.

| Metric | Agreement with labels | Verdict |
|---|---|---|
| AnswerCorrectness | Spearman +0.75 on all 20, but only +0.31 once refusals are removed | Use only to compare configs, never as an absolute score |
| Faithfulness | 87% agreement on real answers | Usable once refusals are excluded (a refusal makes no claims, but Ragas scores it 0) |
| AnswerRelevancy | 100% agreement | Usable, though it mostly separates answers from refusals |

The main problem is AnswerCorrectness: answers labelled fully correct average only 0.51. So a run-level 0.5 does not mean half the answers are wrong. Faithfulness has a blind spot too: the judge sees the text and tables but not the images, so an answer that correctly reads a figure can look unsupported.

### Cost: images dominate the prompt

The median question uses about 3,000 input tokens, but the mean is about 22,000. The 22 questions (of 124) whose context includes images use 90% of all input tokens. The largest single prompt was 400,000 tokens: 32 images from 5 chunks.

The app sends every image in the retrieved chunks at high detail. `gpt-4o-mini` bills a high-detail image at roughly 2,800 tokens plus 5,700 per 512-pixel tile, so even a 160×32 sliver cut from an equation costs over 8,000 tokens. My token estimate matches the billed counts to within 0.6%. Images are 87% of the run's input tokens.

| Option (same 153 images) | Input tokens per run | Input cost per run |
|---|---|---|
| Current: every image at high detail | 2.71M | $0.41 |
| Drop images with a side under 100 px | 2.17M | $0.33 |
| Send images at `detail: "low"` | 0.79M | $0.12 |
| Both | 0.62M | $0.09 |

These would be app changes, so they are recommendations for now. Their effect on answer quality needs its own run.

## Limitations

- **Small sample.** 106 scored dev questions: one question is about one point, and the per-type groups (8 to 61 questions) are smaller still.
- **One corpus.** 40 arXiv papers on distinct topics. A corpus of similar documents (several versions of one policy, say) would make finding the right document harder.
- **Same model generates and judges.** `gpt-4o-mini` does both, to keep costs low. A stronger judge would be more reliable.
- **No agent layer.** The eval scores retrieval and the core answer call, not the agent's final rewrite or the guardrail.
- **Chunking was not tuned yet.** All runs use the app's chunk sizes. See next steps.

## Next steps

In order, once the Cohere key resets:

1. **Finish the hand-label review** of the Ragas check above.
2. **Finalist runs.** Generation + Ragas for baseline, `cps20` and `rerank35-cps20`, reusing their saved rankings so only the 12 unanswerable questions call Cohere (36 calls, about $2.60 in total).
3. **Pick the winner** with paired tests on gold in context and MRR first, then false refusals, cost and AnswerCorrectness changes.
4. **Context size.** Run the winner with 3 and 8 chunks in context instead of 5, to measure the trade between tokens (mostly images) and answer quality.
5. **One chunking variant.** Re-index with smaller chunks (1,500 instead of 3,000 characters) into a separate project and compare. This targets the "right paper, wrong section" problem.
6. **Test split, once.** Baseline and winner on the 82 test questions, reported whatever the result.

Ideas the results point to, but outside the planned runs: better image summaries at ingestion (describe what a figure shows, not just its caption), lower image detail in the prompt, and multi-query search for the paraphrased image questions.

## Reproduce

From `server/`, with the local database running (`./start_db.sh`) and the eval dependencies installed (`poetry install --with eval`):

```bash
python evaluation/open_ragbench/download.py               # seeded subset: PDFs + questions
python -m evaluation.open_ragbench.ingest                 # index 40 papers through the app pipeline
python -m evaluation.open_ragbench.gold --write           # match gold sections to chunks
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/baseline.yaml

python -m evaluation.open_ragbench.pipeline --compare baseline cps20 --by modality
python -m evaluation.open_ragbench.pipeline --paired baseline cps20
```

Each file in `evaluation/open_ragbench/configs/` is one experiment, and its file name is the run name. [`run_experiments.sh`](../evaluation/open_ragbench/run_experiments.sh) lists the sweep in order. Downloaded data and result files are git-ignored. The working notes from the eval (plan, decisions, every run) are in [`evaluation/open_ragbench/notes/`](../evaluation/open_ragbench/notes/).

## Related docs

- [Retrieval Pipeline](RETRIEVAL_PIPELINE.md): the search strategies and the reranker tested here
- [Ingestion Pipeline](INGESTION_PIPELINE.md): how image chunks are summarised, the cause of the weak spot
- [Known Limitations](KNOWN_LIMITATIONS.md)
