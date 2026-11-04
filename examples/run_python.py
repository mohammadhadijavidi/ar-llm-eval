"""Use ar-llm-eval from Python.

    python examples/run_python.py                 # offline, simulated model (DEMO)
    python examples/run_python.py openrouter:qwen/qwen-2.5-72b-instruct   # real run (needs a key)
"""

import sys

from ar_llm_eval.dataset import load_tasks
from ar_llm_eval.leaderboard import render
from ar_llm_eval.runner import RunConfig, run

model = sys.argv[1] if len(sys.argv) > 1 else "mock:noisy-25"
tasks = load_tasks(dialects=["gulf"])  # only the Gulf dialect items
result = run(tasks, RunConfig(model=model, concurrency=4))

s = result["summary"]
print(f"{result['label']}: {s['overall']:.1f}" + ("  (DEMO, simulated)" if result["mock"] else ""))
for name, c in s["categories"].items():
    print(f"  {name:<24}{c['score']:6.1f}")

with open("gulf_leaderboard.html", "w", encoding="utf-8") as fh:
    fh.write(render([result]))
print("wrote gulf_leaderboard.html")
