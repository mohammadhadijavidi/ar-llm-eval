"""Deterministic graders.

Every check takes the model's (cleaned) answer and returns a ``CheckResult``
with a score in ``[0, 1]``. Only ``llm_judge`` calls a model; it is skipped
(and not counted) unless a judge model is configured.

Check types (YAML ``type:``):

``exact``          answer equals one of ``values`` after folding
``keywords``       each group (list of alternatives) must appear; partial credit
``not_contains``   none of ``values`` may appear (whole word by default)
``regex``          ``pattern`` must (``negate: true``: must not) match
``number``         a number in the answer equals ``value`` within ``tolerance``
``choice``         multiple choice: the picked label must equal ``answer``
``word_count``     word count between ``min`` and ``max``
``script``         share of Arabic letters >= ``min_ar`` (or Latin >= ``min_en``)
``diacritics``     diacritic error rate vs. ``reference`` (or item reference) <= ``max_der``;
                   the undiacritized letters must also match the source (``text``)
``root``           the answer names the triliteral/quadriliteral root ``root``
``dialect``        Gulf register: at least ``min_markers`` Gulf markers and at most
                   ``max_msa`` MSA-only markers (lists are built in, extendable)
``json``           a JSON object with required ``keys`` / ``expect`` values
``similarity``     chrF against ``references``; score = min(1, chrF / ``pass_at``)
``llm_judge``      rubric graded by a judge model (only where unavoidable)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from .normalize import (
    diacritic_error_rate,
    extract_number_words,
    extract_numbers,
    find_phrase,
    fold,
    has_diacritics,
    script_ratio,
    strip_diacritics,
    word_count,
)

CHECK_TYPES: dict[str, Callable[..., "CheckResult"]] = {}
FOLD_KEYS = ("alef", "yaa", "taa", "diacritics", "strip_punct", "gulf_letters")


@dataclass
class CheckResult:
    type: str
    score: float
    passed: bool
    detail: str
    weight: float = 1.0
    skipped: bool = False
    required: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type, "score": round(self.score, 4), "passed": self.passed,
                             "detail": self.detail, "weight": self.weight}
        if self.skipped:
            d["skipped"] = True
        if self.required:
            d["required"] = True
        if self.extra:
            d["extra"] = self.extra
        return d


def register(name: str):
    def deco(fn):
        CHECK_TYPES[name] = fn
        return fn

    return deco


def _fold_opts(spec: dict, **defaults) -> dict:
    opts = dict(defaults)
    for k in FOLD_KEYS:
        if k in spec:
            opts[k] = spec[k]
    return opts


def _res(spec: dict, score: float, detail: str, **kw) -> CheckResult:
    score = max(0.0, min(1.0, float(score)))
    return CheckResult(type=spec["type"], score=score, passed=score >= 0.999, detail=detail,
                       weight=float(spec.get("weight", 1.0)), required=bool(spec.get("required", False)), **kw)


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


# ---------------------------------------------------------------------------


@register("exact")
def check_exact(answer: str, spec: dict, **_) -> CheckResult:
    opts = _fold_opts(spec, strip_punct=True)
    got = fold(answer, **opts)
    values = _as_list(spec["values"])
    for v in values:
        if got == fold(str(v), **opts):
            return _res(spec, 1, "matches the expected text")
    return _res(spec, 0, f"does not match any of {len(values)} accepted forms")


@register("keywords")
def check_keywords(answer: str, spec: dict, **_) -> CheckResult:
    opts = _fold_opts(spec, strip_punct=True)
    whole = bool(spec.get("whole_word", True))
    clitics = bool(spec.get("clitics", True))
    got = fold(answer, **opts)
    groups = [_as_list(g) for g in spec["groups"]]
    hits, missing = 0, []
    for g in groups:
        alts = [fold(str(a), **opts) for a in g]
        ok = any(find_phrase(got, a, clitics=clitics) if whole else (a in got) for a in alts if a)
        if ok:
            hits += 1
        else:
            missing.append(str(g[0]))
    score = hits / len(groups) if groups else 1.0
    if spec.get("all_or_nothing"):
        score = 1.0 if hits == len(groups) else 0.0
    detail = f"{hits}/{len(groups)} required elements present"
    if missing:
        detail += "; missing: " + "، ".join(missing)
    return _res(spec, score, detail)


@register("not_contains")
def check_not_contains(answer: str, spec: dict, **_) -> CheckResult:
    opts = _fold_opts(spec, strip_punct=True)
    whole = bool(spec.get("whole_word", True))
    clitics = bool(spec.get("clitics", True))
    got = fold(answer, **opts)
    found = []
    for v in _as_list(spec["values"]):
        fv = fold(str(v), **opts)
        if fv and (find_phrase(got, fv, clitics=clitics) if whole else fv in got):
            found.append(str(v))
    if found:
        return _res(spec, 0, "contains forbidden: " + "، ".join(found))
    return _res(spec, 1, "no forbidden text")


@register("regex")
def check_regex(answer: str, spec: dict, **_) -> CheckResult:
    text = fold(answer, **_fold_opts(spec, lower=False)) if spec.get("fold", False) else answer
    found = re.search(spec["pattern"], text) is not None
    ok = (not found) if spec.get("negate") else found
    what = "absent" if spec.get("negate") else "present"
    return _res(spec, 1 if ok else 0, f"pattern {what}" if ok else f"pattern not {what}")


@register("number")
def check_number(answer: str, spec: dict, **_) -> CheckResult:
    nums = extract_numbers(answer)
    if not nums and spec.get("words", True):
        nums = extract_number_words(answer)
    target = float(spec["value"])
    tol = float(spec.get("tolerance", 1e-6))
    which = spec.get("which", "last")
    if not nums:
        return _res(spec, 0, "no number found")
    cand = nums if which == "any" else nums[:1] if which == "first" else nums[-1:]
    ok = any(abs(n - target) <= tol for n in cand)
    shown = ", ".join(f"{n:g}" for n in cand)
    return _res(spec, 1 if ok else 0, f"found {shown}; expected {target:g}")


_LEADING_RE = re.compile(
    r"^\s*(?:الجواب|الاجابة|الاختيار|الخيار|الحرف|answer|option)?(?:\s+(?:الصحيحة|الصحيح|هو|هي|is))*\s*[:：\-]?\s*",
    re.I,
)


def extract_choice(answer: str, labels: list[str], options: dict[str, str] | None = None) -> str | None:
    """Pick a multiple-choice label out of a free-form answer.

    Accepts ``ب``, ``(ب)``, ``ب)``, ``الجواب: ب``, ``الخيار ب``, ``option B`` and,
    as a fallback, an answer that quotes exactly one option's text.
    """
    raw = fold(answer, strip_punct=False, taa="strict")
    t = _LEADING_RE.sub("", raw, count=1)
    folded = sorted(((fold(lb, taa="strict"), lb) for lb in labels), key=lambda x: -len(x[0]))
    for fl, lb in folded:
        if re.match(rf"^[(\[«\"']?{re.escape(fl)}(?![\wء-ي])", t):
            return lb
    for fl, lb in folded:
        if re.search(rf"(?:الخيار|الاختيار|الحرف|option)\s*[(«\"']?{re.escape(fl)}(?![\wء-ي])", raw):
            return lb
    if options:
        ans = fold(answer, strip_punct=True)
        named = [lb for lb, txt in options.items() if txt and find_phrase(ans, fold(txt, strip_punct=True))]
        if len(named) == 1:
            return named[0]
    return None


@register("choice")
def check_choice(answer: str, spec: dict, item=None, **_) -> CheckResult:
    options = dict(getattr(item, "options", None) or spec.get("options") or {})
    labels = list(options) or [str(x) for x in _as_list(spec.get("labels"))]
    picked = extract_choice(answer, labels, options)
    if picked is None:
        return _res(spec, 0, "could not find a chosen option")
    ok = picked == str(spec["answer"])
    return _res(spec, 1 if ok else 0, f"picked {picked}; correct {spec['answer']}", extra={"picked": picked})


@register("word_count")
def check_word_count(answer: str, spec: dict, **_) -> CheckResult:
    n = word_count(answer)
    lo, hi = int(spec.get("min", 0)), int(spec.get("max", 10 ** 9))
    ok = lo <= n <= hi
    return _res(spec, 1 if ok else 0, f"{n} words (allowed {lo}-{hi if hi < 10 ** 9 else '∞'})")


@register("script")
def check_script(answer: str, spec: dict, **_) -> CheckResult:
    ar, la = script_ratio(answer)
    if "min_en" in spec:
        ok = la >= float(spec["min_en"])
        return _res(spec, 1 if ok else 0, f"Latin letters {la:.0%} (need >= {float(spec['min_en']):.0%})")
    need = float(spec.get("min_ar", 0.9))
    return _res(spec, 1 if ar >= need else 0, f"Arabic letters {ar:.0%} (need >= {need:.0%})")


@register("diacritics")
def check_diacritics(answer: str, spec: dict, item=None, **_) -> CheckResult:
    """Vowelling task. Two things are checked:

    1. the model did not rewrite the sentence: its letters (diacritics removed,
       alef/yaa folded) must equal the source text ``text`` (default: the
       item reference without diacritics); otherwise score 0;
    2. diacritic error rate vs. the reference; full score at DER 0, linear
       down to 0 at ``max_der`` (pass only when DER <= ``pass_der``, default 0).
    """
    refs = [str(r) for r in _as_list(spec.get("references"))] or \
        [str(spec.get("reference") or getattr(item, "reference", "") or "")]
    refs = [r for r in refs if r]
    if not refs:
        return _res(spec, 0, "no vowelled reference")
    answer_line = _first_arabic_line(answer)
    if not has_diacritics(answer_line):
        return _res(spec, 0, "answer has no diacritics", extra={"der": 1.0})
    src = str(spec.get("text") or strip_diacritics(refs[0]))
    key = dict(strip_punct=True, alef="loose", yaa="loose", taa="strict")
    if fold(answer_line, **key).replace(" ", "") != fold(src, **key).replace(" ", ""):
        return _res(spec, 0, "letters differ from the source sentence (text was changed)", extra={"der": 1.0})
    # several references = several valid readings; the closest one counts
    r = min((diacritic_error_rate(answer_line, ref, sukun_optional=bool(spec.get("sukun_optional", True)),
                                  ignore_case_endings=bool(spec.get("ignore_case_endings", False)))
             for ref in refs), key=lambda x: x["der"])
    der = r["der"]
    max_der = float(spec.get("max_der", 0.5))
    pass_der = float(spec.get("pass_der", 0.0))
    if der <= pass_der:
        score = 1.0
    else:
        score = min(0.99, max(0.0, 1 - der / max_der)) if max_der > 0 else 0.0
    detail = f"DER {der:.1%} ({r['errors']}/{r['graded']} marked letters wrong)"
    if r.get("examples"):
        detail += "; expected e.g. " + " ".join(r["examples"])
    return _res(spec, score, detail, extra={"der": round(der, 4)})


def _first_arabic_line(text: str) -> str:
    """Models often add a preamble ("إليك الجملة مشكولة:"). Take the line with
    the most diacritics."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    best = max(lines, key=lambda ln: sum(ch in "ًٌٍَُِّْ" for ch in ln))
    best = re.sub(r"^[^ء-ي]*:\s*", "", best) if ":" in best[:30] else best
    return best.strip(" \"'«»")


_ROOT_SEP_RE = re.compile(r"[\s\-–—_،,.+/|()«»\"']+")


def _root_key(text: str) -> str:
    # roots are compared with hamza seats unified (أ/إ/ؤ/ئ/ء) and alef/yaa folded
    t = re.sub("[ؤئأإآ]", "ء", fold(text, strip_punct=False, alef="strict"))
    return _ROOT_SEP_RE.sub("", t)


@register("root")
def check_root(answer: str, spec: dict, **_) -> CheckResult:
    """The answer must name the root (``ك ت ب``, ``ك-ت-ب``, ``(كتب)`` ...).

    Looks for the root letters written separately, or for the root as a
    token right after a word like ``الجذر``/``جذرها``. A bare one-word
    answer is compared directly.
    """
    want = _as_list(spec["root"])
    keys = {_root_key(str(r)) for r in want}
    t = re.sub("[ؤئأإآ]", "ء", fold(answer, strip_punct=False, alef="strict"))
    # 1) whole answer is the root
    if _root_key(t) in keys:
        return _res(spec, 1, "root matches")
    # 2) letters spelled out with separators: "ك - ت - ب", "ك ت ب"
    for m in re.finditer(r"(?:[ء-ي](?:\s*[\-–—،,/+]?\s*)){2,4}[ء-ي]?", t):
        frag = m.group(0)
        parts = [p for p in _ROOT_SEP_RE.split(frag) if p]
        if len(parts) >= 3 and all(len(p) == 1 for p in parts) and _root_key(frag) in keys:
            return _res(spec, 1, "root matches (spelled out)")
    # 3) "الجذر: كتب" / "جذرها كتب" / "(كتب)"
    for m in re.finditer(r"(?:جذر\w*|root)\s*(?:هو|هي)?\s*[:：]?\s*[(«\"']?([ء-ي]{3,4})", t):
        if _root_key(m.group(1)) in keys:
            return _res(spec, 1, "root matches")
    return _res(spec, 0, f"root {want[0]} not found")


# Common Gulf (Khaleeji, incl. Emirati) markers and MSA-only function words.
# Kept short and high-precision on purpose; tasks can extend both lists.
GULF_MARKERS = [
    "الحين", "هالحين", "وايد", "واجد", "شو", "شلون", "ليش", "وين", "مب", "هب", "أبا", "ابا", "أبي", "ابي",
    "نبا", "نبي", "يبا", "يبي", "تبا", "تبي", "تبون", "باكر", "باچر", "زين", "خوش", "عيل", "هيه", "عسب",
    "بروح", "بسير", "يالس", "يلس", "شحالك", "شحالكم", "بعدين", "شي", "هني", "ويا", "دخيلك", "حياك", "حياكم",
    "يا ريال", "ماعليه", "ما عليه", "تامر", "تامرين", "سيدا", "اشوف", "بس", "خلاص", "ليمن", "شوي", "شوية",
    "عشان", "علشان", "يعطيك العافية", "ميخالف", "هاي", "ذيك", "هذاك", "هلا", "لين", "الصبح", "المسا",
]
# Note: "غداً" (tomorrow) is not listed because, once tanwin is stripped, it is
# spelled like Gulf "غدا" (lunch).
MSA_ONLY_MARKERS = [
    "الآن", "سوف", "لماذا", "ماذا", "أين", "كيف حالك", "لكي", "لن", "ليس", "ليست", "لست", "إنني", "لدي", "لديك",
    "أريد", "نريد", "يريد", "تريد", "كثيراً", "الذي", "التي", "لذلك", "حيث",
]


def _count_markers(text: str, markers: list[str]) -> list[str]:
    t = fold(text, strip_punct=True)
    hits, seen = [], set()
    for m in markers:
        fm = fold(m, strip_punct=True)
        if fm and fm not in seen and find_phrase(t, fm, clitics=True):
            seen.add(fm)
            hits.append(m)
    return hits


@register("dialect")
def check_dialect(answer: str, spec: dict, **_) -> CheckResult:
    """Is the answer written in Gulf Arabic rather than MSA?

    Partial credit: ``min(1, gulf_hits / min_markers)``, zeroed when more than
    ``max_msa`` MSA-only words appear. This is a surface heuristic, not a
    dialect classifier; tasks that need more use ``keywords`` on top.
    """
    gulf = _count_markers(answer, GULF_MARKERS + _as_list(spec.get("extra_markers")))
    msa = _count_markers(answer, [m for m in MSA_ONLY_MARKERS if m not in _as_list(spec.get("allow_msa"))])
    need = int(spec.get("min_markers", 2))
    max_msa = int(spec.get("max_msa", 1))
    score = min(1.0, len(gulf) / need) if need else 1.0
    detail = f"Gulf markers {len(gulf)} (need {need})"
    if gulf:
        detail += ": " + "، ".join(gulf[:5])
    if len(msa) > max_msa:
        score = 0.0
        detail += f"; too many MSA-only words ({len(msa)} > {max_msa}): " + "، ".join(msa[:5])
    return _res(spec, score, detail, extra={"gulf": gulf, "msa": msa})


@register("json")
def check_json(answer: str, spec: dict, **_) -> CheckResult:
    """Answer must be a JSON object (a ```json fence is tolerated) with the
    ``keys``; ``expect`` maps keys to accepted values (folded comparison)."""
    import json

    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer.strip())
    try:
        obj = json.loads(text)
    except ValueError:
        return _res(spec, 0, "not valid JSON")
    if not isinstance(obj, dict):
        return _res(spec, 0, "JSON is not an object")
    keys = [str(k) for k in _as_list(spec.get("keys"))]
    expect = dict(spec.get("expect") or {})
    total = len(keys) + len(expect)
    if total == 0:
        return _res(spec, 1, "valid JSON object")
    ok, problems = 0, []
    for k in keys:
        if k in obj:
            ok += 1
        else:
            problems.append(f"missing key {k}")
    for k, accepted in expect.items():
        got = fold(str(obj.get(k, "")), strip_punct=True)
        if any(got == fold(str(a), strip_punct=True) for a in _as_list(accepted)):
            ok += 1
        else:
            problems.append(f"{k}={obj.get(k)!r}")
    if spec.get("exact_keys") and set(obj) != set(keys):
        return _res(spec, 0, f"keys must be exactly {keys}, got {sorted(obj)}")
    detail = f"{ok}/{total} JSON requirements met" + (("; " + ", ".join(problems)) if problems else "")
    return _res(spec, ok / total, detail)


def chrf(hypothesis: str, reference: str, *, n: int = 6, beta: float = 2.0) -> float:
    """Character n-gram F-score (Popovic 2015), on folded text without spaces."""
    h = fold(hypothesis, strip_punct=True).replace(" ", "")
    r = fold(reference, strip_punct=True).replace(" ", "")
    if not h or not r:
        return 0.0
    precs, recs = [], []
    for k in range(1, n + 1):
        hc = Counter(h[i:i + k] for i in range(len(h) - k + 1))
        rc = Counter(r[i:i + k] for i in range(len(r) - k + 1))
        if not hc or not rc:
            continue
        overlap = sum((hc & rc).values())
        precs.append(overlap / sum(hc.values()))
        recs.append(overlap / sum(rc.values()))
    if not precs:
        return 0.0
    p, rr = sum(precs) / len(precs), sum(recs) / len(recs)
    if p == 0 and rr == 0:
        return 0.0
    b2 = beta * beta
    return 100 * (1 + b2) * p * rr / (b2 * p + rr)


@register("similarity")
def check_similarity(answer: str, spec: dict, item=None, **_) -> CheckResult:
    refs = _as_list(spec.get("references")) or [getattr(item, "reference", "")]
    best = max(chrf(answer, str(r)) for r in refs if r) if any(refs) else 0.0
    pass_at = float(spec.get("pass_at", 50))
    return _res(spec, min(1.0, best / pass_at), f"chrF {best:.1f} (full marks at {pass_at:g})",
                extra={"chrf": round(best, 2)})


JUDGE_PROMPT = """أنت مُقيِّم صارم. قيّم إجابة النموذج وفق المعيار التالي فقط.

السؤال:
{prompt}

المعيار:
{rubric}

إجابة النموذج:
{answer}

أعد سطراً واحداً بالصيغة: SCORE: <رقم من 0 إلى 10>"""


@register("llm_judge")
def check_llm_judge(answer: str, spec: dict, item=None, judge=None, **_) -> CheckResult:
    if judge is None:
        return CheckResult(type="llm_judge", score=0.0, passed=False, detail="skipped (no judge configured)",
                           weight=float(spec.get("weight", 1.0)), skipped=True)
    from .providers import Message

    prompt = JUDGE_PROMPT.format(prompt=getattr(item, "prompt", ""), rubric=spec["rubric"], answer=answer)
    out = judge.complete([Message("user", prompt)], temperature=0.0, max_tokens=50, item=None).text
    m = re.search(r"SCORE\s*[:：]\s*(\d+(?:\.\d+)?)", out) or re.search(r"(\d+(?:\.\d+)?)", out)
    if not m:
        return _res(spec, 0, "judge returned no score", extra={"judge_raw": out[:200]})
    val = min(10.0, float(m.group(1)))
    return _res(spec, val / 10, f"judge score {val:g}/10", extra={"judge_raw": out[:200]})


# ---------------------------------------------------------------------------


def run_checks(answer: str, checks: list[dict], *, item=None, judge=None) -> tuple[float, list[CheckResult]]:
    """Weighted mean of all non-skipped checks. A failed ``required`` check
    zeroes the item."""
    results = [CHECK_TYPES[c["type"]](answer, c, item=item, judge=judge) for c in checks]
    counted = [r for r in results if not r.skipped]
    if not counted:
        return 0.0, results
    if any(r.required and not r.passed for r in counted):
        return 0.0, results
    total_w = sum(r.weight for r in counted)
    score = sum(r.score * r.weight for r in counted) / total_w if total_w else 0.0
    return score, results
