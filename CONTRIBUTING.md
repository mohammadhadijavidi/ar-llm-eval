# Contributing

Contributions are welcome, especially **new hand-written tasks** from native
speakers of Gulf dialects (Emirati, Saudi, Kuwaiti, Qatari, Bahraini, Omani).

## Adding tasks

1. Add items to a file in `src/ar_llm_eval/tasks/` (or create `08_<name>.yaml`).
2. Each item needs a unique `id`, `dialect` (`msa` or `gulf`), `prompt`,
   a hand-written `reference`, and at least one deterministic check.
   Prefer `choice`, `exact`, `root`, `number`, `diacritics`, `json`,
   `keywords`; use `llm_judge` only when nothing deterministic works.
3. Write the items yourself. Do not copy from copyrighted exams, books,
   or other benchmarks, and do not paste model output as a reference.
4. If an item has more than one correct answer, list all of them.
   Add a `note:` explaining anything a reviewer might question.
5. Run:

   ```bash
   ar-llm-eval validate   # every reference must score 100
   pytest -q
   ```

## Publishing results

Only add real results that you produced yourself with `ar-llm-eval run`
and keep the JSON file unedited. Simulated `mock:` runs are always
labelled DEMO and must never be presented as a real model's score.

## Code

Keep dependencies minimal (`httpx`, `PyYAML`). Add a test for every new
check type or provider.
