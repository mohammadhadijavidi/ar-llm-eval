"""Arabic text normalization used by the graders.

Graders must not punish a model for things that are not errors (``12`` vs
``١٢``, ``أ`` vs ``ا`` in a free-form answer, a trailing full stop, tatweel)
while still being able to see the things that *are* errors in some tasks
(diacritics in a vowelling task, hamza placement in a spelling task). So
every helper takes explicit switches instead of doing one "best effort"
cleanup.
"""

from __future__ import annotations

import re
import unicodedata

ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ASCII_DIGITS = "0123456789"
_TO_ASCII = str.maketrans(ARABIC_INDIC_DIGITS + PERSIAN_DIGITS, ASCII_DIGITS * 2)
_TO_ARABIC_INDIC = str.maketrans(ASCII_DIGITS, ARABIC_INDIC_DIGITS)

TATWEEL = "ـ"
SHADDA = "ّ"
SUKUN = "ْ"
FATHATAN = "ً"
DAGGER_ALEF = "ٰ"
# Harakat + tanwin + shadda + sukun (U+064B..U+0652).
HARAKAT = "ًٌٍَُِّْ"
# Everything the grader treats as a diacritic mark (adds maddah/hamza marks,
# dagger alef, Quranic small marks).
_DIACRITIC_CHARS = HARAKAT + "ٕٓٔ" + DAGGER_ALEF + "ۣ۪ۭۖۗۘۙۚۛۜ۟۠ۡۢۤۧۨ"
_DIACRITICS_RE = re.compile(f"[{_DIACRITIC_CHARS}]")

# Zero-width / bidi controls that never carry meaning for grading.
_INVISIBLES = dict.fromkeys(map(ord, "​‌‍‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"), None)

# Letter-variant folding for *meaning* comparison (not for spelling tasks).
_ALEF_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"})
_YAA_MAP = str.maketrans({"ى": "ي", "ی": "ي", "ک": "ك"})
_TAA_MAP = str.maketrans({"ة": "ه"})
# Persian/Urdu letters a model may emit for Gulf words (چ in باچر is fine).
_GULF_LETTERS = str.maketrans({"چ": "ك", "گ": "ق", "ڤ": "ف"})

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[.,!?;:،؛؟«»\"'“”‘’()\[\]{}…\-–—_*`#/\\|<>~]+")

ARABIC_LETTER_RE = re.compile(r"[ء-غف-يٱ-ۓپچژکگی]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


def to_ascii_digits(text: str) -> str:
    return text.translate(_TO_ASCII)


def to_arabic_indic_digits(text: str) -> str:
    return text.translate(_TO_ARABIC_INDIC)


def strip_diacritics(text: str, *, keep_shadda: bool = False) -> str:
    if keep_shadda:
        return re.sub(f"[{_DIACRITIC_CHARS.replace(SHADDA, '')}]", "", text)
    return _DIACRITICS_RE.sub("", text)


def fold(
    text: str,
    *,
    alef: str = "loose",
    yaa: str = "loose",
    taa: str = "loose",
    diacritics: str = "strip",
    strip_punct: bool = False,
    gulf_letters: bool = True,
    lower: bool = True,
) -> str:
    """Return a comparison key for ``text``.

    ``alef``        ``"loose"``: أ إ آ ٱ -> ا. ``"strict"``: kept.
    ``yaa``         ``"loose"``: ى -> ي (also Persian ی/ک). ``"strict"``: kept.
    ``taa``         ``"loose"``: ة -> ه. ``"strict"``: kept.
    ``diacritics``  ``"strip"`` removes harakat/tanwin/shadda/sukun, ``"keep"`` keeps them.
    ``gulf_letters`` maps چ/گ/ڤ to ك/ق/ف so ``باچر`` == ``باكر``.

    Tatweel, invisible bidi/zero-width characters and digit scripts are always
    normalized (digits become ASCII).
    """
    if not text:
        return ""
    for opt, val in (("alef", alef), ("yaa", yaa), ("taa", taa)):
        if val not in ("loose", "strict"):
            raise ValueError(f"{opt} must be 'loose' or 'strict', got {val!r}")
    if diacritics not in ("strip", "keep"):
        raise ValueError(f"diacritics must be 'strip' or 'keep', got {diacritics!r}")
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLES)
    text = text.replace(TATWEEL, "").replace(" ", " ").replace(" ", " ")
    if diacritics == "strip":
        text = _DIACRITICS_RE.sub("", text)
    if alef == "loose":
        text = text.translate(_ALEF_MAP)
    if yaa == "loose":
        text = text.translate(_YAA_MAP)
    if taa == "loose":
        text = text.translate(_TAA_MAP)
    if gulf_letters:
        text = text.translate(_GULF_LETTERS)
    text = to_ascii_digits(text)
    if strip_punct:
        text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text.lower() if lower else text


_WORD_CHAR = r"[\wء-ي]"
# One-letter proclitics that attach to the next word: و ف ب ل ك (and the article).
_PROCLITIC = r"(?:[وفبلك]{0,2}(?:ال)?)"


def find_phrase(haystack: str, needle: str, *, clitics: bool = False) -> bool:
    """Whole-word search: ``علم`` does not match ``معلم``.

    With ``clitics=True`` the needle may carry attached proclitics
    (``والحين``, ``بالحين`` match ``الحين``; ``وايد`` matches ``ووايد``).
    Both strings must already be folded with the same options.
    """
    if not needle:
        return False
    prefix = _PROCLITIC if clitics else ""
    pattern = rf"(?<!{_WORD_CHAR}){prefix}{re.escape(needle)}(?!{_WORD_CHAR})"
    return re.search(pattern, haystack) is not None


# --- numbers ---------------------------------------------------------------

_NUM_RE = re.compile(r"(?<![\d.])-?\d+(?:[,٬]\d{3})*(?:[.٫]\d+)?")


def extract_numbers(text: str) -> list[float]:
    """All numbers in ``text`` (Arabic-Indic, Persian or ASCII digits; ``٬``/``,``
    thousands separators; ``٫``/``.`` decimal separators).

    ``٧٣٤٫٥`` -> 734.5, ``١٬٢٥٠`` -> 1250. Units are not expanded; tasks state
    the unit they want.
    """
    t = unicodedata.normalize("NFC", text).translate(_TO_ASCII)
    out: list[float] = []
    for m in _NUM_RE.finditer(t):
        raw = re.sub(r"[,٬](?=\d{3})", "", m.group(0)).replace("٫", ".")
        try:
            out.append(float(raw))
        except ValueError:  # pragma: no cover - regex guarantees a number
            continue
    return out


# Small cardinal words (folded spelling) so "سبع" / "سبعة إمارات" count as 7.
_NUMBER_WORDS = {
    "صفر": 0, "واحد": 1, "واحده": 1, "اثنان": 2, "اثنين": 2, "اثنتان": 2, "ثلاث": 3, "ثلاثه": 3,
    "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6, "سبع": 7, "سبعه": 7,
    "ثمان": 8, "ثماني": 8, "ثمانيه": 8, "تسع": 9, "تسعه": 9, "عشر": 10, "عشره": 10,
    "احد عشر": 11, "اثنا عشر": 12, "اثني عشر": 12, "عشرون": 20, "عشرين": 20, "مئه": 100, "مائه": 100,
}


def extract_number_words(text: str) -> list[float]:
    """Numbers written as single Arabic words (0-12, 20, 100). Compound
    numbers like "ثلاثة آلاف" are deliberately not parsed: tasks that need
    them ask for digits."""
    t = fold(text, strip_punct=True)
    out: list[float] = []
    for w, v in sorted(_NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(rf"(?<![\wء-ي])[وفب]?(?:ال)?{w}(?![\wء-ي])", t):
            out.append((m.start(), float(v)))  # type: ignore[arg-type]
            t = t[:m.start()] + " " * (m.end() - m.start()) + t[m.end():]
    return [v for _, v in sorted(out)]  # type: ignore[misc]


def word_count(text: str) -> int:
    t = fold(text, strip_punct=True)
    return len(t.split()) if t else 0


def script_ratio(text: str) -> tuple[float, float]:
    """(Arabic-script share, Latin share) among letters in ``text``."""
    ar = len(ARABIC_LETTER_RE.findall(text))
    la = len(LATIN_LETTER_RE.findall(text))
    total = ar + la
    if total == 0:
        return 0.0, 0.0
    return ar / total, la / total


# --- diacritics ------------------------------------------------------------

_BASE_FOLD = str.maketrans({"ٱ": "ا"})


def letters_with_marks(text: str) -> list[tuple[str, frozenset[str]]]:
    """Split vowelled text into ``(base_letter, marks)`` pairs.

    Only Arabic letters are kept (spaces, punctuation and digits are
    dropped). Dagger alef and tatweel are ignored; alef wasla is read as alef.
    A *fathatan* written on a word-final alef/alef maqsura (``صباحاً``) is moved
    to the preceding letter, so both common spellings compare equal.
    """
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLES).replace(TATWEEL, "")
    out: list[list] = []      # [base, marks, is_word_final]
    for ch in text:
        if ch in HARAKAT:
            if out:
                out[-1][1].add(ch)
        elif ch in _DIACRITIC_CHARS:  # dagger alef, small Quranic marks: ignore
            continue
        elif ARABIC_LETTER_RE.match(ch):
            if out and out[-1][2] is None:
                out[-1][2] = False
            out.append([ch.translate(_BASE_FOLD), set(), None])
        elif out and out[-1][2] is None:
            out[-1][2] = True
    if out and out[-1][2] is None:
        out[-1][2] = True
    for k in range(1, len(out)):
        base, marks, final = out[k]
        if final and base in "اى" and marks == {FATHATAN} and not (out[k - 1][1] - {SHADDA}):
            out[k - 1][1].add(FATHATAN)
            out[k][1] = set()
    return [(b, frozenset(m)) for b, m, _ in out]


def _word_final_positions(text: str) -> set[int]:
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLES).replace(TATWEEL, "")
    finals: set[int] = set()
    n = 0
    prev_letter = False
    for ch in text:
        if ch in _DIACRITIC_CHARS:
            continue
        if ARABIC_LETTER_RE.match(ch):
            n += 1
            prev_letter = True
        else:
            if prev_letter:
                finals.add(n - 1)
            prev_letter = False
    if prev_letter:
        finals.add(n - 1)
    return finals


def diacritic_error_rate(
    predicted: str,
    reference: str,
    *,
    sukun_optional: bool = True,
    ignore_case_endings: bool = False,
) -> dict:
    """Diacritic error rate (DER) of ``predicted`` against a vowelled ``reference``.

    Base letters are aligned with :mod:`difflib` so a model that changes or
    drops a word only loses the letters it touched. Every reference letter that
    carries a mark is a graded position; it is correct when the aligned
    predicted letter carries exactly the same set of marks. Reference letters
    that the model deleted or replaced count as errors.

    ``sukun_optional``      sukun is removed on both sides first (many careful
                            writers leave it out, and its absence is not a
                            reading error).
    ``ignore_case_endings`` skip the last letter of every reference word
                            (the classic "DER without case ending").
    """
    import difflib

    def prep(text: str) -> list[tuple[str, frozenset[str]]]:
        pairs = letters_with_marks(text)
        if sukun_optional:
            pairs = [(b, m - {SUKUN}) for b, m in pairs]
        return pairs

    ref = prep(reference)
    pred = prep(predicted)
    ref_finals = _word_final_positions(reference) if ignore_case_endings else set()
    graded = [i for i, (_, m) in enumerate(ref) if m and not (ignore_case_endings and i in ref_finals)]
    if not graded:
        return {"der": 0.0, "errors": 0, "graded": 0, "aligned": 0}
    sm = difflib.SequenceMatcher(a=[b for b, _ in ref], b=[b for b, _ in pred], autojunk=False)
    mapping: dict[int, int] = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            mapping[blk.a + k] = blk.b + k
    errors = 0
    examples: list[str] = []
    for i in graded:
        j = mapping.get(i)
        if j is None or pred[j][1] != ref[i][1]:
            errors += 1
            if len(examples) < 4:
                examples.append(ref[i][0] + "".join(sorted(ref[i][1])))
    aligned = sum(1 for i in graded if i in mapping)
    return {
        "der": errors / len(graded),
        "errors": errors,
        "graded": len(graded),
        "aligned": aligned,
        "examples": examples,
    }


def has_diacritics(text: str) -> bool:
    return any(ch in HARAKAT for ch in text)
