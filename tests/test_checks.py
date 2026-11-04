import pytest

from ar_llm_eval.checks import chrf, extract_choice, run_checks
from ar_llm_eval.dataset import Item

OPTS = {"أ": "قليلاً", "ب": "كثيراً / جداً", "ج": "أحياناً", "د": "فجأة"}


def one(answer, spec, item=None):
    score, res = run_checks(answer, [spec], item=item)
    return score, res[0]


@pytest.mark.parametrize("answer", ["ب", "(ب)", "ب) كثيراً", "الجواب: ب", "الإجابة الصحيحة هي ب", "الخيار ب لأن...",
                                    "كثيراً / جداً"])
def test_extract_choice_formats(answer):
    assert extract_choice(answer, list(OPTS), OPTS) == "ب"


def test_extract_choice_none():
    assert extract_choice("لا أعرف", list(OPTS), OPTS) is None


def test_choice_check():
    item = Item(id="x", category="c", dialect="gulf", prompt="p", checks=[], options=OPTS)
    assert one("ب", {"type": "choice", "answer": "ب"}, item)[0] == 1
    assert one("أ", {"type": "choice", "answer": "ب"}, item)[0] == 0


def test_exact_folding():
    assert one("أبوظبي.", {"type": "exact", "values": ["أبوظبي", "أبو ظبي"]})[0] == 1
    assert one("ابو ظبي", {"type": "exact", "values": ["أبوظبي", "أبو ظبي"]})[0] == 1
    assert one("دبي", {"type": "exact", "values": ["أبوظبي"]})[0] == 0


def test_exact_strict_taa():
    spec = {"type": "exact", "taa": "strict", "values": ["مهندستان"]}
    assert one("مهندستان", spec)[0] == 1


def test_keywords_partial_and_clitics():
    spec = {"type": "keywords", "groups": [["الشارقة"], ["دبي"]]}
    assert one("ذهبت إلى الشارقة", spec)[0] == 0.5
    assert one("بالشارقة ودبي", spec)[0] == 1


def test_not_contains_strict_spelling():
    spec = {"type": "not_contains", "alef": "strict", "yaa": "strict", "taa": "strict", "values": ["الي", "المدرسه"]}
    assert one("ذهبت إلى المدرسة", spec)[0] == 1
    assert one("ذهبت الي المدرسة", spec)[0] == 0


def test_number_check_arabic_digits_and_words():
    assert one("الجواب ٢٥٢ درهماً", {"type": "number", "value": 252})[0] == 1
    assert one("سبع", {"type": "number", "value": 7})[0] == 1
    assert one("لا أدري", {"type": "number", "value": 7})[0] == 0


def test_root_check_formats():
    spec = {"type": "root", "root": "كتب"}
    for ans in ["ك ت ب", "ك-ت-ب", "ك - ت - ب", "الجذر: كتب", "كتب", "جذرها (ك ت ب)"]:
        assert one(ans, spec)[0] == 1, ans
    assert one("ك ت م", spec)[0] == 0


def test_root_hamza_seats_unified():
    assert one("س ء ل", {"type": "root", "root": "سأل"})[0] == 1


def test_diacritics_check():
    ref = "إِنَّ العِلْمَ نُورٌ"
    item = Item(id="d", category="diacritics", dialect="msa", prompt="p", checks=[], reference=ref)
    spec = {"type": "diacritics", "max_der": 0.4}
    assert one(ref, spec, item)[0] == 1
    assert one("إليك الجملة مشكولة:\n" + ref, spec, item)[0] == 1  # preamble tolerated
    assert one("إن العلم نور", spec, item)[0] == 0  # no diacritics
    s, r = one("إِنَّ العِلْمِ نُورٌ", spec, item)
    assert 0 < s < 1 and not r.passed
    assert one("إِنَّ المَعْرِفَةَ نُورٌ", spec, item)[0] == 0  # text changed


def test_dialect_check():
    spec = {"type": "dialect", "min_markers": 2, "max_msa": 0}
    assert one("أبا أروح البيت الحين لأني تعبان وايد", spec)[0] == 1
    assert one("أريد أن أذهب إلى البيت الآن", spec)[0] == 0
    assert one("أبا أروح الحين", {"type": "dialect", "min_markers": 4})[0] == 0.5


def test_dialect_lunch_is_not_msa_tomorrow():
    # Gulf "غدا" (lunch) folds like MSA "غداً" (tomorrow) and must not count as MSA
    _, r = one("عندنا غدا في البيت، حياكم", {"type": "dialect", "min_markers": 1, "max_msa": 0})
    assert r.passed


def test_json_check():
    spec = {"type": "json", "keys": ["name", "city"], "expect": {"city": ["الشارقة"]}}
    assert one('{"name": "سارة", "city": "الشارقة"}', spec)[0] == 1
    assert one('```json\n{"name": "سارة", "city": "الشارقه"}\n```', spec)[0] == 1
    assert one("ليس JSON", spec)[0] == 0


def test_regex_script_word_count():
    assert one("١٢٥٠", {"type": "regex", "pattern": "^[٠-٩]+$"})[0] == 1
    assert one("مرحبا", {"type": "script", "min_ar": 1.0})[0] == 1
    assert one("Welcome to Dubai", {"type": "script", "min_en": 1.0})[0] == 1
    assert one("واحد اثنان ثلاثة", {"type": "word_count", "max": 2})[0] == 0


def test_required_zeroes_item():
    checks = [{"type": "exact", "values": ["نعم"], "required": True}, {"type": "script", "min_ar": 0.5}]
    assert run_checks("لا", checks)[0] == 0


def test_llm_judge_skipped_without_judge():
    score, res = run_checks("x", [{"type": "llm_judge", "rubric": "r"}, {"type": "exact", "values": ["x"]}])
    assert res[0].skipped and score == 1


def test_chrf():
    assert chrf("مرحبا بكم", "مرحبا بكم") == pytest.approx(100)
    assert chrf("abc", "xyz") == 0
