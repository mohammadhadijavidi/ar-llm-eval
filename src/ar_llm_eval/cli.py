"""Command line: ``ar-llm-eval run | board | validate | list | demo | grade``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .checks import run_checks
from .dataset import DatasetError, load_tasks
from .leaderboard import render
from .providers import ProviderError, load_dotenv
from .runner import RunConfig, load_results, run, save_result

DEMO_MODELS = [
    ("mock:oracle", "Oracle (reference answers)"),
    ("mock:noisy-25", "Simulated: 25% noise"),
    ("mock:no-diacritics+noisy-15", "Simulated: no tashkeel"),
    ("mock:msa-only+noisy-20", "Simulated: MSA-only"),
    ("mock:noisy-55", "Simulated: 55% noise"),
    ("mock:random", "Random guesser"),
]


def _tasks(args) -> list:
    cats = args.category.split(",") if getattr(args, "category", None) else None
    dias = args.dialect.split(",") if getattr(args, "dialect", None) else None
    return load_tasks(args.tasks or None, categories=cats, dialects=dias)


def _add_task_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tasks", nargs="*", help="task YAML files or directories (default: built-in seed set)")
    p.add_argument("--category", help="comma-separated categories to include")
    p.add_argument("--dialect", help="msa, gulf or msa,gulf")


def cmd_run(args) -> int:
    cats = _tasks(args)
    cfg = RunConfig(model=args.model, label=args.label, judge=args.judge, temperature=args.temperature,
                    max_tokens=args.max_tokens, concurrency=args.concurrency, limit=args.limit, seed=args.seed)

    def progress(done: int, total: int, r: dict) -> None:
        if args.quiet:
            return
        mark = "ERR" if r.get("error") else f"{r['score'] * 100:5.1f}"
        print(f"\r[{done:>3}/{total}] {r['id']:<10} {mark}", end="", file=sys.stderr, flush=True)

    result = run(cats, cfg, progress=progress)
    if not args.quiet:
        print(file=sys.stderr)
    path = save_result(result, args.out)
    s = result["summary"]
    flag = "  [DEMO: simulated mock model, not a real LLM]" if result["mock"] else ""
    print(f"{result['label']}: overall {s['overall']:.1f}{flag}")
    for name, c in s["categories"].items():
        print(f"  {name:<22} {c['score']:5.1f}  (n={c['n']})")
    for d, c in s["dialects"].items():
        print(f"  dialect:{d:<14} {c['score']:5.1f}  (n={c['n']})")
    if s["errors"]:
        print(f"  {s['errors']} items failed with provider errors (scored 0)", file=sys.stderr)
    print(f"saved {path}")
    return 0


def cmd_board(args) -> int:
    results = load_results(args.results)
    if not results:
        print("no result files found", file=sys.stderr)
        return 1
    html = render(results, digits=args.digits, show_items=not args.no_items)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(results)} models)")
    return 0


def cmd_demo(args) -> int:
    """Run the built-in simulated models and build a DEMO leaderboard."""
    cats = load_tasks()
    out = Path(args.out)
    for spec, label in DEMO_MODELS:
        res = run(cats, RunConfig(model=spec, label=label, concurrency=8))
        save_result(res, out / "results")
        print(f"{label:<30} {res['summary']['overall']:5.1f}  (DEMO)")
    html = render(load_results([out / "results"]), digits=args.digits)
    (out / "leaderboard.html").write_text(html, encoding="utf-8")
    print(f"wrote {out / 'leaderboard.html'}  (all rows are DEMO / simulated)")
    return 0


def cmd_validate(args) -> int:
    """Self-test: every item's reference answer must get full marks."""
    cats = _tasks(args)
    bad = 0
    total = 0
    for c in cats:
        for it in c.items:
            total += 1
            if not it.reference:
                print(f"WARN {it.id}: no reference answer")
                continue
            score, results = run_checks(it.reference, it.checks, item=it)
            counted = [r for r in results if not r.skipped]
            if counted and score < 0.999:
                bad += 1
                why = "; ".join(r.detail for r in results if not r.passed)
                print(f"FAIL {it.id}: reference scores {score:.2f} ({why})")
    n_cats = len(cats)
    print(f"{total} items in {n_cats} categories; {bad} reference failures")
    return 1 if bad else 0


def cmd_list(args) -> int:
    cats = _tasks(args)
    for c in cats:
        dia = {d: sum(1 for it in c.items if it.dialect == d) for d in ("msa", "gulf")}
        print(f"{c.name:<22} {len(c.items):>3} items  msa={dia['msa']:<3} gulf={dia['gulf']:<3} {c.title_en}")
    return 0


def cmd_grade(args) -> int:
    """Grade one answer against one item (handy when writing new tasks)."""
    cats = load_tasks(args.tasks or None)
    item = next((it for c in cats for it in c.items if it.id == args.item), None)
    if item is None:
        print(f"no item {args.item!r}", file=sys.stderr)
        return 1
    answer = sys.stdin.read() if args.answer == "-" else args.answer
    score, results = run_checks(answer, item.checks, item=item)
    print(json.dumps({"id": item.id, "score": round(score, 4), "checks": [r.to_dict() for r in results]},
                     ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ar-llm-eval", description="Arabic + Gulf dialect LLM benchmark")
    p.add_argument("--version", action="version", version=f"ar-llm-eval {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="evaluate one model")
    r.add_argument("--model", required=True, help="<provider>:<model>, e.g. openrouter:qwen/qwen-2.5-72b-instruct")
    r.add_argument("--label", help="display name on the leaderboard")
    r.add_argument("--judge", help="judge model for llm_judge checks (optional)")
    r.add_argument("--out", default="results", help="output directory (default: results)")
    r.add_argument("--temperature", type=float, default=0.0)
    r.add_argument("--max-tokens", type=int, default=1024)
    r.add_argument("--concurrency", type=int, default=4)
    r.add_argument("--limit", type=int, help="first N items per category (smoke tests)")
    r.add_argument("--seed", type=int, default=0, help="seed for mock models")
    r.add_argument("-q", "--quiet", action="store_true")
    _add_task_args(r)
    r.set_defaults(fn=cmd_run)

    b = sub.add_parser("board", help="build the HTML leaderboard from result files")
    b.add_argument("results", nargs="*", default=["results"])
    b.add_argument("--out", default="leaderboard.html")
    b.add_argument("--digits", choices=["arabic", "latin"], default="arabic")
    b.add_argument("--no-items", action="store_true", help="omit per-item details")
    b.set_defaults(fn=cmd_board)

    d = sub.add_parser("demo", help="run simulated models offline and build a DEMO leaderboard")
    d.add_argument("--out", default="demo")
    d.add_argument("--digits", choices=["arabic", "latin"], default="arabic")
    d.set_defaults(fn=cmd_demo)

    v = sub.add_parser("validate", help="check that every reference answer scores 100")
    _add_task_args(v)
    v.set_defaults(fn=cmd_validate)

    ls = sub.add_parser("list", help="list categories and item counts")
    _add_task_args(ls)
    ls.set_defaults(fn=cmd_list)

    g = sub.add_parser("grade", help="grade one answer for one item id")
    g.add_argument("item")
    g.add_argument("answer", help="answer text, or - for stdin")
    g.add_argument("--tasks", nargs="*")
    g.set_defaults(fn=cmd_grade)
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except (DatasetError, ProviderError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
