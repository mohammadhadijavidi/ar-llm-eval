import json

import pytest

from ar_llm_eval.checks import run_checks
from ar_llm_eval.dataset import DatasetError, load_tasks, tasks_fingerprint
from ar_llm_eval.leaderboard import render
from ar_llm_eval.providers import Message, Mock, ProviderError, get_provider, parse_model_spec
from ar_llm_eval.runner import RunConfig, clean_answer, load_results, run, save_result


@pytest.fixture(scope="module")
def cats():
    return load_tasks()


def test_seed_set_shape(cats):
    names = {c.name for c in cats}
    assert {"diacritics", "dialect_understanding", "dialect_writing", "morphology", "orthography",
            "uae_context", "instructions"} <= names
    items = [it for c in cats for it in c.items]
    assert len(items) >= 70
    assert sum(it.dialect == "gulf" for it in items) >= 20
    assert all(it.source == "hand-written" for it in items)


def test_every_reference_gets_full_marks(cats):
    for c in cats:
        for it in c.items:
            score, res = run_checks(it.reference, it.checks, item=it)
            assert score == pytest.approx(1.0), (it.id, [r.detail for r in res])


def test_filters(cats):
    gulf = load_tasks(dialects=["gulf"])
    assert all(it.dialect == "gulf" for c in gulf for it in c.items)
    assert [c.name for c in load_tasks(categories=["morphology"])] == ["morphology"]
    with pytest.raises(DatasetError):
        load_tasks(categories=["nope"])


def test_bad_task_file(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("category: x\nitems:\n  - id: a\n    prompt: p\n    checks: [{type: nope}]\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="unknown check"):
        load_tasks([p])
    p.write_text("category: x\nitems:\n  - id: a\n    prompt: p\n    options: {أ: x, ب: y}\n"
                 "    checks: [{type: choice, answer: ج}]\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="not an option"):
        load_tasks([p])


def test_fingerprint_changes_with_content(cats):
    fp = tasks_fingerprint(cats)
    cats2 = load_tasks()
    cats2[0].items[0].prompt += " "
    assert tasks_fingerprint(cats2) != fp


def test_provider_specs(monkeypatch):
    assert parse_model_spec("openrouter:qwen/qwen-2.5-72b") == ("openrouter", "qwen/qwen-2.5-72b")
    with pytest.raises(ProviderError):
        parse_model_spec("qwen")
    with pytest.raises(ProviderError):
        parse_model_spec("foo:bar")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        get_provider("openai:gpt-4o-mini")
    p = get_provider("ollama:qwen2.5:7b")
    assert p.base_url.endswith("/v1") and p.model == "qwen2.5:7b"
    with pytest.raises(ProviderError):
        Mock("bogus")


def test_openai_compatible_request(monkeypatch):
    import httpx

    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>x</think>ب"}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    p = get_provider("openrouter:some/model")
    out = p.complete([Message("system", "s"), Message("user", "u")])
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert clean_answer(out.text) == "ب"


def test_anthropic_request(monkeypatch):
    import httpx

    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "نعم"}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    out = get_provider("anthropic:claude-x").complete([Message("system", "s"), Message("user", "u")])
    assert out.text == "نعم" and seen["json"]["system"] == "s"
    assert all(m["role"] != "system" for m in seen["json"]["messages"])


def test_client_error_not_retried(monkeypatch):
    import httpx

    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        return httpx.Response(401, text="bad key", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    with pytest.raises(ProviderError, match="401"):
        get_provider("groq:m", retries=3).complete([Message("user", "u")])
    assert len(calls) == 1


def test_oracle_scores_100_and_is_flagged_mock(cats):
    res = run(cats, RunConfig(model="mock:oracle"))
    assert res["mock"] is True
    assert res["summary"]["overall"] == 100.0
    assert res["summary"]["errors"] == 0


def test_simulations_hit_the_right_categories(cats):
    nod = run(cats, RunConfig(model="mock:no-diacritics"))["summary"]["categories"]
    msa = run(cats, RunConfig(model="mock:msa-only"))["summary"]["categories"]
    assert nod["diacritics"]["score"] < 50 and nod["morphology"]["score"] > 90
    assert msa["dialect_writing"]["score"] < 75 and msa["morphology"]["score"] == 100


def test_mock_is_deterministic(cats):
    a = run(cats, RunConfig(model="mock:noisy-30"))["summary"]["overall"]
    b = run(cats, RunConfig(model="mock:noisy-30"))["summary"]["overall"]
    assert a == b


def test_provider_errors_score_zero(cats, monkeypatch):
    import ar_llm_eval.providers as prov

    def boom(self, *a, **k):
        raise ProviderError("down")

    monkeypatch.setattr(prov.Mock, "complete", boom)
    res = run(cats, RunConfig(model="mock:oracle", limit=1))
    assert res["summary"]["errors"] == len(cats)
    assert res["summary"]["overall"] == 0


def test_save_load_render(tmp_path, cats):
    res = run(cats, RunConfig(model="mock:noisy-20", label="Sim"))
    path = save_result(res, tmp_path)
    loaded = load_results([tmp_path])
    assert len(loaded) == 1 and json.loads(path.read_text(encoding="utf-8"))["label"] == "Sim"
    html = render(loaded)
    assert 'dir="rtl"' in html and "DEMO" in html and "Sim" in html
    assert "@font-face" in html


def test_render_real_run_has_no_demo_banner(tmp_path, cats):
    res = run(cats, RunConfig(model="mock:oracle"))
    res["mock"] = False  # pretend a real run
    html = render([res])
    assert 'class="banner"' not in html
