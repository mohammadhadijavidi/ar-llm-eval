#!/usr/bin/env bash
# Compare several models and build one leaderboard.
# Needs keys in .env (see .env.example). Mock models need nothing.
set -euo pipefail

MODELS=(
  "openrouter:qwen/qwen-2.5-72b-instruct"
  "openrouter:meta-llama/llama-3.3-70b-instruct"
  "ollama:qwen2.5:7b"
)

for m in "${MODELS[@]}"; do
  ar-llm-eval run --model "$m" --out results || echo "skipped $m"
done

ar-llm-eval board results --out leaderboard.html
echo "open leaderboard.html"
