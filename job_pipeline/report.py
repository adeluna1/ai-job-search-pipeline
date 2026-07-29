"""Generate self-contained HTML and CSV views of ranked jobs."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from .util import utc_now


def _e(value: Any) -> str:
    """HTML-escape one value for safe report rendering."""
    return html.escape(str(value or ""), quote=True)


def _chips(values: list[str], css_class: str = "chip") -> str:
    """Render short string values as compact HTML chips."""
    return "".join(f'<span class="{css_class}">{_e(value)}</span>' for value in values)


def _list_items(values: list[str], empty: str) -> str:
    """Render values as list items, with an explicit empty-state message."""
    if not values:
        return f"<li>{_e(empty)}</li>"
    return "".join(f"<li>{_e(value)}</li>" for value in values)


def _card(record: dict[str, Any]) -> str:
    """Render one joined database record as a scorecard."""
    score = float(record["final_score"])
    score_class = "great" if score >= 82 else "strong" if score >= 72 else "possible" if score >= 60 else "weak"
    components = record.get("components", {})
    component_rows = "".join(
        f"<div><span>{_e(name.title())}</span><b>{float(value):.0f}</b></div>"
        for name, value in components.items()
    )
    ai_line = ""
    if record.get("ai_score") is not None:
        ai_line = f'<p class="ai">AI score: {_e(record["ai_score"])}. {_e(record.get("ai_reason"))}</p>'
    salary = f'<span class="meta">{_e(record["salary"])}</span>' if record.get("salary") else ""
    return f"""
    <article class="job-card {score_class}" data-score="{score:.1f}" data-fit="{_e(record['fit_label'])}" data-status="{_e(record.get('status', 'new'))}" data-mode="{_e(record.get('work_mode', 'unknown'))}">
      <div class="card-head">
        <div>
          <p class="eyebrow">{_e(record['company'])}</p>
          <h2><a href="{_e(record['url'])}">{_e(record['title'])}</a></h2>
          <div class="meta-row"><span class="meta">{_e(record['location'])}</span><span class="meta">{_e(record['work_mode'])}</span>{salary}</div>
        </div>
        <div class="score"><strong>{score:.0f}</strong><span>{_e(record['fit_label'])}</span></div>
      </div>
      <p class="recommendation">{_e(record['recommendation'])}</p>
      {ai_line}
      <div class="components">{component_rows}</div>
      <div class="detail-grid">
        <section><h3>Matched evidence</h3><div class="chips">{_chips(record.get('matched_skills', [])[:10])}</div><ul>{_list_items(record.get('matched_evidence', []), 'No resume evidence mapped automatically.')}</ul></section>
        <section><h3>Gaps to verify</h3><ul>{_list_items(record.get('gaps', []), 'No material gap was detected by the configured rubric.')}</ul></section>
      </div>
      <footer><code>{_e(record['id'])}</code><span>Status: {_e(record.get('status', 'new'))}</span><span>{_e(record.get('posted_date', ''))}</span></footer>
    </article>
    """


def export_html(
    records: list[dict[str, Any]],
    path: Path,
    threshold: float,
    *,
    title: str = "AI job match shortlist",
    subtitle: str = (
        "Evidence-based rankings derived from the configured resume profile. "
        "Verify every role on the employer's site before applying."
    ),
) -> None:
    """Write an interactive, offline HTML shortlist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    strong_count = sum(float(record["final_score"]) >= threshold for record in records)
    companies = len({record["company"].casefold() for record in records})
    cards = "\n".join(_card(record) for record in records)
    generated = utc_now()
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<style>
:root{{--ink:#17212b;--muted:#647184;--paper:#f3f6f8;--card:#fff;--navy:#15324a;--teal:#168478;--gold:#cc8b19;--red:#b64c4c;--line:#dce4e8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 Inter,Segoe UI,Arial,sans-serif}}a{{color:inherit}}.shell{{max-width:1120px;margin:auto;padding:44px 24px 70px}}header.hero{{background:linear-gradient(130deg,var(--navy),#1c5361);color:#fff;border-radius:22px;padding:34px;box-shadow:0 18px 50px #15324a22}}.hero h1{{margin:0 0 8px;font-size:clamp(30px,5vw,50px);line-height:1.05}}.hero p{{margin:0;max-width:760px;color:#d9e8ec}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:26px}}.stat{{background:#ffffff14;border:1px solid #ffffff22;border-radius:13px;padding:15px}}.stat strong{{display:block;font-size:27px}}.toolbar{{position:sticky;top:0;z-index:4;margin:22px 0;padding:13px;background:#f3f6f8ee;backdrop-filter:blur(10px);display:flex;gap:10px;flex-wrap:wrap}}input,select{{border:1px solid var(--line);background:#fff;border-radius:10px;padding:11px 12px;font:inherit}}input{{flex:1;min-width:220px}}.job-card{{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--muted);border-radius:16px;padding:24px;margin:15px 0;box-shadow:0 8px 28px #1836420c}}.job-card.great{{border-left-color:var(--teal)}}.job-card.strong{{border-left-color:#3b8fbb}}.job-card.possible{{border-left-color:var(--gold)}}.job-card.weak{{border-left-color:var(--red)}}.card-head{{display:flex;justify-content:space-between;gap:20px}}h2{{margin:2px 0 8px;font-size:24px;line-height:1.18}}h2 a{{text-decoration:none}}h2 a:hover{{text-decoration:underline}}.eyebrow{{text-transform:uppercase;letter-spacing:.11em;color:var(--muted);font-weight:700;font-size:12px;margin:0}}.score{{min-width:88px;text-align:center;background:var(--paper);border-radius:13px;padding:10px}}.score strong{{display:block;font-size:31px;line-height:1}}.score span{{font-size:12px;text-transform:uppercase;color:var(--muted)}}.meta-row,.chips{{display:flex;gap:7px;flex-wrap:wrap}}.meta,.chip{{background:#edf2f4;border-radius:999px;padding:4px 9px;font-size:12px}}.chip{{background:#e3f3ef;color:#105e56}}.recommendation{{font-weight:700;color:var(--navy)}}.ai{{border-left:3px solid #8a63bb;padding-left:10px;color:#564367}}.components{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:17px 0}}.components div{{background:var(--paper);padding:8px;border-radius:8px;display:flex;justify-content:space-between}}.detail-grid{{display:grid;grid-template-columns:1.2fr 1fr;gap:25px}}h3{{font-size:13px;text-transform:uppercase;letter-spacing:.08em;margin:12px 0 8px;color:var(--muted)}}ul{{padding-left:20px}}footer{{border-top:1px solid var(--line);padding-top:12px;margin-top:16px;display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:12px}}.empty{{padding:40px;text-align:center}}@media(max-width:720px){{.stats,.components,.detail-grid{{grid-template-columns:1fr}}.card-head{{align-items:flex-start}}}}
</style></head><body><main class="shell">
<header class="hero"><h1>{_e(title)}</h1><p>{_e(subtitle)}</p><div class="stats"><div class="stat"><strong>{len(records)}</strong>ranked jobs</div><div class="stat"><strong>{strong_count}</strong>strong fits (&ge; {threshold:g})</div><div class="stat"><strong>{companies}</strong>companies</div></div></header>
<div class="toolbar"><input id="search" type="search" placeholder="Filter title, company, or location"><select id="fit"><option value="">All fit levels</option><option>excellent</option><option>strong</option><option>possible</option><option>weak</option></select><select id="mode"><option value="">All work modes</option><option>remote</option><option>hybrid</option><option>onsite</option><option>unknown</option></select><select id="status"><option value="">All statuses</option><option>new</option><option>saved</option><option>applied</option><option>interviewing</option><option>offer</option><option>rejected</option><option>withdrawn</option></select></div>
<section id="cards">{cards or '<p class="empty">No scored jobs meet this report cutoff.</p>'}</section>
<p class="generated">Generated {_e(generated)}. Scores are decision support, not hiring guarantees.</p>
</main><script>
const q=document.querySelector('#search'),fit=document.querySelector('#fit'),mode=document.querySelector('#mode'),status=document.querySelector('#status');
function filterCards(){{const term=q.value.toLowerCase();document.querySelectorAll('.job-card').forEach(card=>{{const show=card.textContent.toLowerCase().includes(term)&&(!fit.value||card.dataset.fit===fit.value)&&(!mode.value||card.dataset.mode===mode.value)&&(!status.value||card.dataset.status===status.value);card.hidden=!show}})}}
[q,fit,mode,status].forEach(el=>el.addEventListener('input',filterCards));
</script></body></html>"""
    path.write_text(document, encoding="utf-8", newline="\n")


def export_csv(records: list[dict[str, Any]], path: Path) -> None:
    """Write a spreadsheet-friendly shortlist with explanations in compact columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "final_score", "deterministic_score", "ai_score", "fit_label", "status",
        "title", "company", "location", "work_mode", "posted_date", "salary", "url",
        "matched_skills", "gaps", "recommendation", "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field, "") for field in fields}
            row["matched_skills"] = "; ".join(record.get("matched_skills", []))
            row["gaps"] = "; ".join(record.get("gaps", []))
            writer.writerow(row)


def export_reports(
    records: list[dict[str, Any]],
    report_dir: Path,
    threshold: float,
    prefix: str = "job_matches",
    *,
    title: str = "AI job match shortlist",
    subtitle: str = (
        "Evidence-based rankings derived from the configured resume profile. "
        "Verify every role on the employer's site before applying."
    ),
) -> tuple[Path, Path]:
    """Export both supported report formats and return their paths."""
    html_path = report_dir / f"{prefix}.html"
    csv_path = report_dir / f"{prefix}.csv"
    export_html(records, html_path, threshold, title=title, subtitle=subtitle)
    export_csv(records, csv_path)
    return html_path, csv_path
