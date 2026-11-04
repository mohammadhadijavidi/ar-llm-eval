from ar_llm_eval.normalize import (
    diacritic_error_rate, extract_number_words, extract_numbers, find_phrase, fold, letters_with_marks,
    script_ratio, strip_diacritics, word_count,
)

REF = "ذَهَبَ الوَلَدُ إِلَى المَدْرَسَةِ صَبَاحًا"


def test_fold_alef_yaa_taa_digits_tatweel():
    assert fold("إلى المدرسة ١٢") == fold("الي المدرسه 12")
    assert fold("أهـــلاً") == "اهلا"
    assert fold("مدرسة", taa="strict") != fold("مدرسه", taa="strict")
    assert fold("إلى", alef="strict", yaa="strict") != fold("الي", alef="strict", yaa="strict")


def test_fold_keeps_diacritics_when_asked():
    assert fold("كَتَبَ", diacritics="keep") == "كَتَبَ"
    assert fold("كَتَبَ") == "كتب"


def test_gulf_letters():
    assert fold("باچر") == fold("باكر")


def test_find_phrase_whole_word_and_clitics():
    assert not find_phrase("معلم", "علم")
    assert find_phrase(fold("والحين بروح"), "الحين", clitics=True)
    assert not find_phrase(fold("والحين"), "الحين", clitics=False)


def test_extract_numbers_arabic_indic():
    assert extract_numbers("السعر ٧٣٤٫٥ درهم و ١٬٢٥٠") == [734.5, 1250.0]
    assert extract_numbers("1,050 AED") == [1050.0]


def test_number_words():
    assert extract_number_words("عددها سبع إمارات") == [7.0]
    assert extract_number_words("سبعة") == [7.0]
    assert extract_number_words("ستين") == []


def test_word_count_and_script():
    assert word_count("مرحباً بكم في دبي!") == 4
    ar, la = script_ratio("مرحبا Dubai")
    assert 0.4 < ar < 0.6 and 0.4 < la < 0.6


def test_letters_with_marks_fathatan_on_alef_equivalent():
    assert letters_with_marks("صَبَاحاً") == letters_with_marks("صَبَاحًا")


def test_der_perfect_and_one_error():
    assert diacritic_error_rate(REF, REF)["der"] == 0
    r = diacritic_error_rate("ذَهَبَ الوَلَدِ إِلَى المَدْرَسَةِ صَبَاحًا", REF)
    assert r["errors"] == 1 and r["graded"] == 15


def test_der_sukun_optional():
    no_sukun = REF.replace("ْ", "")
    assert diacritic_error_rate(no_sukun, REF)["der"] == 0
    assert diacritic_error_rate(no_sukun, REF, sukun_optional=False)["der"] > 0


def test_der_ignore_case_endings():
    wrong_end = "ذَهَبَ الوَلَدِ إِلَى المَدْرَسَةَ صَبَاحًا"
    assert diacritic_error_rate(wrong_end, REF)["errors"] == 2
    assert diacritic_error_rate(wrong_end, REF, ignore_case_endings=True)["errors"] == 0


def test_der_undiacritized_is_total_error():
    assert diacritic_error_rate(strip_diacritics(REF), REF)["der"] == 1.0
