"""Render result files as one self-contained RTL HTML leaderboard.

The page embeds the Noto Sans Arabic font (OFL) so it renders the same
offline, has no JavaScript dependency, and shows a DEMO banner plus a DEMO
tag on every row that came from a simulated (``mock``) model.
"""

from __future__ import annotations

import base64
import html
from importlib import resources
from typing import Any

from . import __version__

AR_DIGITS = str.maketrans("0123456789.", "٠١٢٣٤٥٦٧٨٩٫")

DEMO_BANNER_AR = (
    "نتائج تجريبية (DEMO): هذه الأرقام صادرة عن نماذج محاكاة <code dir=\"ltr\">mock</code> "
    "وليست قياساً لأي نموذج لغوي حقيقي. للحصول على نتائج حقيقية شغّل: "
    "<code dir=\"ltr\">ar-llm-eval run --model openrouter:&lt;model&gt;</code>"
)
DEMO_BANNER_EN = "Demo results from simulated mock models. Not measurements of any real language model."

CSS = """
:root{--bg:#0b0f14;--panel:#121821;--panel2:#18202b;--line:#232d3a;--ink:#e8edf3;--muted:#8a97a8;
--accent:#2fbf9f;--accent2:#d9b25f;--warn:#e0a03a;--warnbg:#2a1f0e;--bad:#e06a5a}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font-family:"Noto Sans Arabic","Segoe UI",Tahoma,sans-serif;font-size:15px;line-height:1.6}
.wrap{max-width:1500px;margin:0 auto;padding:28px 32px 40px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap;margin-bottom:18px}
h1{font-size:30px;margin:0;font-weight:700;letter-spacing:0}
h1 .en{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:15px;color:var(--accent);font-weight:500;
display:block;margin-bottom:2px;direction:ltr;text-align:right}
.sub{color:var(--muted);margin:4px 0 0;font-size:14px}
.meta{display:flex;gap:10px;flex-wrap:wrap}
.chip{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:13px;color:var(--muted)}
.chip b{color:var(--ink);font-weight:600}
.banner{background:var(--warnbg);border:1px solid #5a4116;color:#f3d29a;border-radius:10px;padding:10px 16px;
margin:0 0 18px;font-size:14px;display:flex;gap:12px;align-items:center}
.banner .tag{background:var(--warn);color:#1b1408;font-weight:700;border-radius:6px;padding:1px 8px;font-size:12px;
font-family:ui-monospace,Menlo,monospace;flex:none}
.banner code,.foot code{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;background:#00000040;padding:1px 6px;border-radius:4px}
.banner .en{display:block;color:#c9a96b;font-size:12.5px;direction:ltr;text-align:right}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
table{border-collapse:collapse;width:100%}
.card{overflow-x:auto}
th,td{padding:10px 8px;text-align:center;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--panel2);color:var(--muted);font-weight:600;font-size:13px;vertical-align:bottom}
th .en{display:block;font-family:ui-monospace,Menlo,monospace;font-size:10.5px;color:#5f6d7f;font-weight:400;direction:ltr}
th.grp{border-bottom:1px solid var(--line);font-size:12px;color:var(--accent2);padding:6px}
tr:last-child td{border-bottom:none}
td.rank{color:var(--muted);font-family:ui-monospace,Menlo,monospace;width:44px}
td.model{text-align:right;min-width:230px}
.mname{font-weight:600;direction:ltr;unicode-bidi:isolate;display:inline-block}
.mspec{display:block;color:var(--muted);font-family:ui-monospace,Menlo,monospace;font-size:11.5px;direction:ltr;text-align:right}
.demo{background:var(--warn);color:#1b1408;font-weight:700;border-radius:5px;padding:0 6px;font-size:10.5px;
font-family:ui-monospace,Menlo,monospace;margin-inline-start:8px;vertical-align:2px}
td.overall{min-width:170px}
.bar{display:flex;align-items:center;gap:10px;justify-content:flex-start}
.bar .track{flex:1;height:8px;background:#1f2834;border-radius:99px;overflow:hidden;direction:rtl}
.bar .fill{height:100%;background:linear-gradient(270deg,var(--accent),#1f8f78);border-radius:99px}
.bar .num{font-weight:700;font-size:17px;min-width:48px;text-align:left;font-variant-numeric:tabular-nums}
td.s{font-variant-numeric:tabular-nums;font-weight:600;font-size:14px}
td.s span{display:inline-block;min-width:52px;padding:3px 8px;border-radius:7px}
td.split{color:var(--muted);font-size:13px}
.sep{border-inline-start:1px solid var(--line)}
.foot{margin-top:16px;color:var(--muted);font-size:13px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
.foot a{color:var(--accent);text-decoration:none}
details{margin-top:22px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 16px}
summary{cursor:pointer;color:var(--ink);font-weight:600}
.items{width:100%;margin-top:10px;font-size:13px}
.items td,.items th{white-space:normal;text-align:right;padding:6px 8px}
.items td.id{font-family:ui-monospace,Menlo,monospace;direction:ltr;text-align:left;color:var(--muted);white-space:nowrap}
.items td.ans{max-width:520px;color:#c7d0db}
.ok{color:var(--accent)}.ko{color:var(--bad)}
.legend{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:22px;height:10px;border-radius:3px}
"""


def _font_face() -> str:
    fonts = resources.files("ar_llm_eval") / "web" / "fonts"
    out = []
    for weight, files in ((400, ("noto-sans-arabic-arabic-400-normal.woff2", "noto-sans-arabic-latin-400-normal.woff2")),
                          (700, ("noto-sans-arabic-arabic-700-normal.woff2", "noto-sans-arabic-latin-700-normal.woff2"))):
        for f, rng in zip(files, ("U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+200C-200F",
                                  "U+0000-00FF,U+2000-206F")):
            data = base64.b64encode((fonts / f).read_bytes()).decode()
            out.append(f"@font-face{{font-family:'Noto Sans Arabic';font-weight:{weight};font-display:swap;"
                       f"src:url(data:font/woff2;base64,{data}) format('woff2');unicode-range:{rng}}}")
    return "\n".join(out)


def ar_num(v: float | int | None, digits: str = "arabic") -> str:
    """Format a score (one decimal) or an int count in Arabic-Indic or ASCII digits."""
    if v is None:
        return "—"
    s = str(v) if isinstance(v, int) else f"{v:.1f}"
    return s.translate(AR_DIGITS) if digits == "arabic" else s


def score_color(v: float | None) -> tuple[str, str]:
    """Sequential teal scale (dark -> bright) for cell backgrounds; text stays readable."""
    if v is None:
        return "transparent", "var(--muted)"
    t = max(0.0, min(1.0, v / 100))
    # interpolate #1a2430 -> #1f9e83
    a, b = (0x1a, 0x24, 0x30), (0x1f, 0x9e, 0x83)
    rgb = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    ink = "#f2fbf8" if t > 0.45 else "#c9d3de"
    return "#%02x%02x%02x" % rgb, ink


def _category_columns(results: list[dict]) -> list[tuple[str, str, str]]:
    cols: list[tuple[str, str, str]] = []
    seen = set()
    for r in results:
        for name, c in r["summary"]["categories"].items():
            if name not in seen:
                seen.add(name)
                cols.append((name, c.get("title_ar", name), c.get("title_en", name)))
    return cols


def render(results: list[dict[str, Any]], *, title: str = "لوحة نتائج النماذج اللغوية بالعربية واللهجة الخليجية",
           digits: str = "arabic", show_items: bool = True) -> str:
    if not results:
        raise ValueError("no result files to render")
    rows = sorted(results, key=lambda r: -r["summary"]["overall"])
    cols = _category_columns(rows)
    any_mock = any(r.get("mock") for r in rows)
    versions = sorted({r.get("tasks_version", "?") for r in rows})
    n_items = max(r["summary"]["n_items"] for r in rows)
    esc = html.escape

    head = ['<tr><th rowspan="2">#</th><th rowspan="2" style="text-align:right">النموذج<span class="en" '
            'style="text-align:right">model</span></th><th rowspan="2">المعدل العام<span class="en">overall</span></th>',
            f'<th class="grp sep" colspan="{len(cols)}">الفئات</th>',
            '<th class="grp sep" colspan="2">حسب اللهجة</th></tr><tr>']
    for i, (_, ar, en) in enumerate(cols):
        head.append(f'<th class="{"sep" if i == 0 else ""}">{esc(ar)}<span class="en">{esc(en)}</span></th>')
    head.append('<th class="sep">فصحى<span class="en">MSA</span></th><th>خليجي<span class="en">Gulf</span></th></tr>')

    body = []
    for rank, r in enumerate(rows, 1):
        s = r["summary"]
        tag = '<span class="demo">DEMO</span>' if r.get("mock") else ""
        cells = [f'<td class="rank">{ar_num(rank, digits)}</td>',
                 f'<td class="model"><span class="mname">{esc(r.get("label") or r["model"])}</span>{tag}'
                 f'<span class="mspec">{esc(r["model"])}</span></td>',
                 f'<td class="overall"><div class="bar"><div class="track"><div class="fill" '
                 f'style="width:{s["overall"]:.1f}%"></div></div><span class="num">{ar_num(s["overall"], digits)}</span>'
                 f'</div></td>']
        for i, (name, _, _) in enumerate(cols):
            v = s["categories"].get(name, {}).get("score")
            bg, ink = score_color(v)
            cells.append(f'<td class="s{" sep" if i == 0 else ""}"><span style="background:{bg};color:{ink}">'
                         f'{ar_num(v, digits)}</span></td>')
        for i, d in enumerate(("msa", "gulf")):
            v = s["dialects"].get(d, {}).get("score")
            cells.append(f'<td class="split{" sep" if i == 0 else ""}">{ar_num(v, digits)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")

    banner = ""
    if any_mock:
        banner = (f'<div class="banner"><span class="tag">DEMO</span><div>{DEMO_BANNER_AR}'
                  f'<span class="en">{DEMO_BANNER_EN}</span></div></div>')

    details = ""
    if show_items:
        parts = []
        for r in rows:
            trs = []
            for it in r["items"]:
                ok = it["score"] >= 0.999
                why = "; ".join(c["detail"] for c in it.get("checks", []) if not c.get("passed")) or it.get("error", "")
                ans = (it.get("answer") or "")[:220]
                trs.append(f'<tr><td class="id">{esc(it["id"])}</td><td class="{"ok" if ok else "ko"}">'
                           f'{ar_num(it["score"] * 100, digits)}</td><td class="ans" dir="auto">{esc(ans)}</td>'
                           f'<td dir="auto">{esc(why)}</td></tr>')
            parts.append(f'<details><summary>{esc(r.get("label") or r["model"])}'
                         f'{" — DEMO" if r.get("mock") else ""}: تفاصيل البنود ({len(r["items"])})</summary>'
                         f'<table class="items"><tr><th>البند</th><th>الدرجة</th><th>الإجابة</th><th>سبب الخصم</th></tr>'
                         f'{"".join(trs)}</table></details>')
        details = "".join(parts)

    date = max(r.get("created", "") for r in rows)[:10]
    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{_font_face()}
{CSS}</style></head>
<body><div class="wrap">
<header><div><h1><span class="en">ar-llm-eval</span>{esc(title)}</h1>
<p class="sub">مجموعة بذرية مكتوبة يدوياً: التشكيل، فهم اللهجة الخليجية والكتابة بها، الصرف، الإملاء، المعرفة الإماراتية، اتباع التعليمات. التصحيح آلي وحتمي.</p></div>
<div class="meta"><span class="chip">البنود <b>{ar_num(n_items, digits)}</b></span>
<span class="chip">النماذج <b>{ar_num(len(rows), digits)}</b></span>
<span class="chip" dir="ltr">tasks <b>{esc(", ".join(versions))}</b></span>
<span class="chip" dir="ltr">{esc(date)}</span></div></header>
{banner}
<div class="card"><table><thead>{"".join(head)}</thead><tbody>{"".join(body)}</tbody></table></div>
<div class="foot"><span>المعدل العام = متوسط الفئات بأوزان متساوية (macro). الدرجات من ١٠٠.</span>
<span class="legend">٠ <i style="background:{score_color(0)[0]}"></i><i style="background:{score_color(50)[0]}"></i><i style="background:{score_color(100)[0]}"></i> ١٠٠</span>
<span dir="ltr">ar-llm-eval v{__version__} · <a href="https://github.com/mohammadhadijavidi/ar-llm-eval">github.com/mohammadhadijavidi/ar-llm-eval</a></span></div>
{details}
</div></body></html>"""
