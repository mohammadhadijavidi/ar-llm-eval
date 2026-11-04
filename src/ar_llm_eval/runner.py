"""Run a model over the tasks and write a JSON result file.

Result schema (``results/<slug>.json``)::

    {
      "schema": "ar-llm-eval/1",
      "model": "openrouter:qwen/qwen-2.5-72b-instruct",
      "label": "Qwen2.5 72B",            # optional display name
      "mock": false,                      # true for simulated models -> DEMO
      "created": "2026-11-04T10:00:00Z",
      "tasks_version": "<sha>",           # fingerprint of the task content
      "settings": {...},
      "summary": {"overall": 71.3, "categories": {...}, "dialects": {...}, "n_items": 60, "errors": 0},
      "items": [{"id": ..., "score": ..., "answer": ..., "checks": [...]}, ...]
    }
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .checks import run_checks
from .dataset import Category, Item, tasks_fingerprint
from .providers import Message, ProviderError, get_provider

SCHEMA = "ar-llm-eval/1"

DEFAULT_SYSTEM = (
    "أنت مساعد دقيق. أجب عن السؤال مباشرة وباختصار، دون مقدمات أو شرح إلا إذا طُلب منك ذلك."
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")


def clean_answer(text: str) -> str:
    """Remove reasoning blocks (``<think>``) and a wrapping code fence."""
    text = _THINK_RE.sub("", text or "").strip()
    return _FENCE_RE.sub("", text).strip()


@dataclass
class RunConfig:
    model: str
    label: str | None = None
    judge: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    concurrency: int = 4
    limit: int | None = None
    seed: int = 0
    system: str = DEFAULT_SYSTEM


def _eval_item(item: Item, provider, judge, cfg: RunConfig) -> dict[str, Any]:
    msgs = [Message("system", item.system or cfg.system), Message("user", item.render_prompt())]
    t0 = time.perf_counter()
    try:
        comp = provider.complete(msgs, temperature=cfg.temperature, max_tokens=cfg.max_tokens, item=item)
    except ProviderError as e:
        return {"id": item.id, "category": item.category, "dialect": item.dialect, "score": 0.0,
                "error": str(e)[:500], "answer": "", "checks": [], "latency_s": round(time.perf_counter() - t0, 3)}
    answer = clean_answer(comp.text)
    score, results = run_checks(answer, item.checks, item=item, judge=judge)
    return {
        "id": item.id, "category": item.category, "dialect": item.dialect, "score": round(score, 4),
        "answer": answer, "checks": [r.to_dict() for r in results], "latency_s": round(comp.latency_s, 3),
        "usage": comp.usage,
    }


def summarize(items: list[dict], categories: list[Category]) -> dict[str, Any]:
    """Macro average: each category weighs the same, whatever its size."""
    by_cat: dict[str, list[float]] = {}
    by_dia: dict[str, list[float]] = {}
    for r in items:
        by_cat.setdefault(r["category"], []).append(r["score"])
        by_dia.setdefault(r["dialect"], []).append(r["score"])
    cats = {}
    for c in categories:
        vals = by_cat.get(c.name, [])
        if vals:
            cats[c.name] = {"score": round(100 * sum(vals) / len(vals), 1), "n": len(vals),
                            "title_ar": c.title_ar, "title_en": c.title_en}
    overall = round(sum(v["score"] for v in cats.values()) / len(cats), 1) if cats else 0.0
    dias = {d: {"score": round(100 * sum(v) / len(v), 1), "n": len(v)} for d, v in sorted(by_dia.items())}
    return {"overall": overall, "categories": cats, "dialects": dias, "n_items": len(items),
            "errors": sum(1 for r in items if r.get("error"))}


def run(categories: list[Category], cfg: RunConfig, *,
        progress: Callable[[int, int, dict], None] | None = None) -> dict[str, Any]:
    provider = get_provider(cfg.model, seed=cfg.seed)
    judge = get_provider(cfg.judge) if cfg.judge else None
    work: list[Item] = []
    for c in categories:
        work += c.items[: cfg.limit] if cfg.limit else c.items
    results: list[dict | None] = [None] * len(work)
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, cfg.concurrency)) as pool:
        futs = {pool.submit(_eval_item, it, provider, judge, cfg): i for i, it in enumerate(work)}
        for fut in futs:
            i = futs[fut]
            results[i] = fut.result()
            done += 1
            if progress:
                progress(done, len(work), results[i])
    items = [r for r in results if r is not None]
    used = [Category(c.name, c.title_ar, c.title_en, c.description, [it for it in c.items if it in work])
            for c in categories]
    return {
        "schema": SCHEMA,
        "tool_version": __version__,
        "model": cfg.model,
        "label": cfg.label or cfg.model.split(":", 1)[1],
        "mock": bool(getattr(provider, "is_mock", False)),
        "judge": cfg.judge,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tasks_version": tasks_fingerprint(used),
        "settings": {"temperature": cfg.temperature, "max_tokens": cfg.max_tokens, "limit": cfg.limit,
                     "seed": cfg.seed},
        "summary": summarize(items, used),
        "items": items,
    }


def slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-").lower() or "run"


def save_result(result: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slugify(result['model'])}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_results(paths: list[str | Path]) -> list[dict]:
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    out = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            continue
        data["_file"] = str(f)
        out.append(data)
    return out
