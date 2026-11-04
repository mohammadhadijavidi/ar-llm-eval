"""Task files: loading and validation.

A task file is YAML with a ``category`` header and a list of ``items``::

    category: diacritics
    title_ar: التشكيل
    title_en: Diacritization
    items:
      - id: dia-001
        dialect: msa            # msa | gulf
        prompt: "شكّل الجملة ..."
        reference: "ذَهَبَ ..."  # hand-written gold answer
        checks:
          - {type: diacritics, max_der: 0.15}

Every item is hand-written. ``reference`` is the gold answer used to
self-test the graders (``ar-llm-eval validate`` runs every check on it and
fails if the reference does not get full marks).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

DIALECTS = ("msa", "gulf")


class DatasetError(ValueError):
    pass


@dataclass
class Item:
    id: str
    category: str
    dialect: str
    prompt: str
    checks: list[dict[str, Any]]
    reference: str = ""
    options: dict[str, str] | None = None
    system: str | None = None
    tags: list[str] = field(default_factory=list)
    note: str = ""
    source: str = "hand-written"

    def render_prompt(self) -> str:
        if not self.options:
            return self.prompt.strip()
        lines = [self.prompt.strip(), ""]
        lines += [f"{k}) {v}" for k, v in self.options.items()]
        lines += ["", "اكتب حرف الخيار الصحيح فقط."]
        return "\n".join(lines)


@dataclass
class Category:
    name: str
    title_ar: str
    title_en: str
    description: str
    items: list[Item]
    path: str = ""


def builtin_tasks_dir() -> Path:
    return Path(str(resources.files("ar_llm_eval") / "tasks"))


def _load_file(path: Path) -> Category:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DatasetError(f"{path.name}: invalid YAML: {e}") from e
    if not isinstance(data, dict) or "items" not in data or "category" not in data:
        raise DatasetError(f"{path.name}: needs 'category' and 'items'")
    cat = str(data["category"])
    items: list[Item] = []
    for i, raw in enumerate(data["items"] or []):
        where = f"{path.name} item #{i + 1}"
        if not isinstance(raw, dict):
            raise DatasetError(f"{where}: must be a mapping")
        for key in ("id", "prompt", "checks"):
            if key not in raw:
                raise DatasetError(f"{where}: missing '{key}'")
        dialect = str(raw.get("dialect", data.get("dialect", "msa")))
        if dialect not in DIALECTS:
            raise DatasetError(f"{where}: dialect must be one of {DIALECTS}, got {dialect!r}")
        checks = raw["checks"]
        if not isinstance(checks, list) or not checks:
            raise DatasetError(f"{where}: 'checks' must be a non-empty list")
        options = raw.get("options")
        if options is not None:
            if not isinstance(options, dict) or len(options) < 2:
                raise DatasetError(f"{where}: 'options' must map at least two labels to texts")
            options = {str(k): str(v) for k, v in options.items()}
        items.append(Item(
            id=str(raw["id"]), category=cat, dialect=dialect, prompt=str(raw["prompt"]),
            checks=[dict(c) for c in checks], reference=str(raw.get("reference", "")),
            options=options, system=raw.get("system"), tags=list(raw.get("tags", [])),
            note=str(raw.get("note", "")), source=str(raw.get("source", "hand-written")),
        ))
    return Category(name=cat, title_ar=str(data.get("title_ar", cat)), title_en=str(data.get("title_en", cat)),
                    description=str(data.get("description", "")), items=items, path=str(path))


def load_tasks(paths: list[str | Path] | None = None, *, categories: list[str] | None = None,
               dialects: list[str] | None = None) -> list[Category]:
    """Load task files from ``paths`` (files or directories; default: built-in set)."""
    from .checks import CHECK_TYPES  # local import: checks imports nothing from here at module load

    files: list[Path] = []
    for p in (paths or [builtin_tasks_dir()]):
        p = Path(p)
        if p.is_dir():
            files += sorted(p.glob("*.yaml")) + sorted(p.glob("*.yml"))
        elif p.is_file():
            files.append(p)
        else:
            raise DatasetError(f"no such task file or directory: {p}")
    cats: dict[str, Category] = {}
    seen: dict[str, str] = {}
    for f in files:
        c = _load_file(f)
        for it in c.items:
            if it.id in seen:
                raise DatasetError(f"duplicate item id {it.id!r} in {f.name} and {seen[it.id]}")
            seen[it.id] = f.name
            for chk in it.checks:
                if chk.get("type") not in CHECK_TYPES:
                    raise DatasetError(f"{it.id}: unknown check type {chk.get('type')!r}")
                if chk["type"] == "choice" and not it.options:
                    raise DatasetError(f"{it.id}: 'choice' check needs item 'options'")
                if chk["type"] == "choice" and str(chk.get("answer")) not in (it.options or {}):
                    raise DatasetError(f"{it.id}: choice answer {chk.get('answer')!r} is not an option")
        if c.name in cats:
            cats[c.name].items += c.items
        else:
            cats[c.name] = c
    out = list(cats.values())
    if categories:
        unknown = set(categories) - {c.name for c in out}
        if unknown:
            raise DatasetError(f"unknown categories: {', '.join(sorted(unknown))}")
        out = [c for c in out if c.name in categories]
    if dialects:
        for c in out:
            c.items = [it for it in c.items if it.dialect in dialects]
        out = [c for c in out if c.items]
    return out


def tasks_fingerprint(categories: list[Category]) -> str:
    """Stable hash of the task content, stored with every run so results from
    different task versions are not silently mixed on one leaderboard."""
    blob = [
        {"id": it.id, "prompt": it.prompt, "options": it.options, "checks": it.checks, "system": it.system}
        for c in categories for it in c.items
    ]
    return hashlib.sha256(json.dumps(blob, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
