# Phase C: rerank sweep, RETRIEVAL-ONLY on dev (no generation, no Ragas). Run from server/.
# Run one at a time: the Cohere trial key allows 10 calls/min. About 15 min each.
# About 112 Cohere calls per run: check the trial key's monthly cap first.

# OpenAI cost: question embeddings only, under $0.001 per run
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/cps20.yaml
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/cps30.yaml
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/cps20-thr02.yaml
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/cps30-thr02.yaml
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/rerank35-cps20.yaml
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/hybrid-cps20.yaml
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/hybrid-cps20-kw05.yaml
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/hybrid-cps20-kw07.yaml

# Multi-query: one extra gpt-4o-mini call + 3-5 embeddings per question, about $0.02-0.03 per run.
# Not approved yet: uncomment after the OK.
# python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/mq-vector-cps20.yaml
# python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/mq-vector-cps20-nq3.yaml
# python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/mq-hybrid-cps20.yaml

# C4: compare everything against the baseline, split by text-only vs with-image
python -m evaluation.open_ragbench.pipeline --compare all --by modality --vs baseline
# then, per config: python -m evaluation.open_ragbench.pipeline --paired baseline <config>
# and for one-setting changes from cps20: python -m evaluation.open_ragbench.pipeline --paired cps20 <config>

# ---------------------------------------------------------------------------------------------
# Phase D: finalists with generation + Ragas on dev (124 questions each, incl. 12 unanswerable).
# --reuse-retrieval takes the ranked lists from the retrieval-only runs: only the 12 unanswerable
# questions call Cohere (36 calls in total). Estimated OpenAI cost about $0.70-0.80 per run.
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/baseline.yaml --overwrite --reuse-retrieval baseline
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/cps20.yaml --overwrite --reuse-retrieval cps20
python -m evaluation.open_ragbench.pipeline --config evaluation/open_ragbench/configs/rerank35-cps20.yaml --overwrite --reuse-retrieval rerank35-cps20

# D2: compare the finalists
python -m evaluation.open_ragbench.pipeline --compare baseline cps20 rerank35-cps20 --by modality
python -m evaluation.open_ragbench.pipeline --paired baseline cps20
python -m evaluation.open_ragbench.pipeline --paired baseline rerank35-cps20
python -m evaluation.open_ragbench.pipeline --paired cps20 rerank35-cps20
