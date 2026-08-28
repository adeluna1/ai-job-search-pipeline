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
    intelligence = record.get("posting_intelligence", {}) or {}
    trust = intelligence.get("trust", {}) or {}
    repost = intelligence.get("repost", {}) or {}
    cross_listings = intelligence.get("cross_listings", []) or []
    intelligence_line = ""
    if trust:
        signals = list(trust.get("flags", []))
        if repost.get("detected"):
            signals.append(f"reposted {repost.get('appearance_count', 2)} times")
        if cross_listings:
            signals.append(f"{len(cross_listings)} near-duplicate cross-listing(s)")
        signal_text = ", ".join(signals) if signals else "No deterministic concern detected."
        intelligence_line = (
            f'<p class="intelligence"><strong>Posting confidence: '
            f'{_e(str(trust.get("level", "unknown")).title())} '
            f'({_e(trust.get("score", ""))}/100)</strong>: {_e(signal_text)} '
            f'<span>Advisory only; resume score unchanged.</span></p>'
        )
    return f"""
    <article class="job-card {score_class}" data-score="{score:.1f}" data-fit="{_e(record['fit_label'])}" data-status="{_e(record.get('status', 'new'))}" data-mode="{_e(record.get('work_mode', 'unknown'))}">
      <div class="card-head">
        <div>
          <h2><a href="{_e(record['url'])}">{_e(record['title'])} &mdash; {_e(record['company'])}</a></h2>
          <div class="meta-row"><span class="meta">{_e(record['location'])}</span><span class="meta">{_e(record['work_mode'])}</span>{salary}</div>
        </div>
        <div class="score"><strong>{score:.0f}</strong><span>{_e(record['fit_label'])}</span></div>
      </div>
      <p class="recommendation">{_e(record['recommendation'])}</p>
      {ai_line}
      {intelligence_line}
      <div class="components">{component_rows}</div>
      <div class="detail-grid">
        <section><h3>Matched evidence</h3><div class="chips">{_chips(record.get('matched_skills', [])[:10])}</div><ul>{_list_items(record.get('matched_evidence', []), 'No resume evidence mapped automatically.')}</ul></section>
        <section><h3>Gaps to verify</h3><ul>{_list_items(record.get('gaps', []), 'No material gap was detected by the configured rubric.')}</ul></section>
      </div>
      <footer><code>{_e(record['id'])}</code><span>Status: {_e(record.get('status', 'new'))}</span><span>{_e(record.get('posted_date', ''))}</span></footer>
    </article>
    """


def _manual_card(record: dict[str, Any]) -> str:
    """Render an unverified lead without presenting it as an application candidate."""
    employer = (
        f'<a href="{_e(record.get("employer_url"))}">Employer/ATS lead</a>'
        if record.get("employer_url") else "No employer URL confirmed"
    )
    return f"""
    <article class="manual-card" data-disposition="manual_verification_required">
      <p class="eyebrow">Manual verification required</p>
      <h2><a href="{_e(record.get('source_url'))}">{_e(record.get('title'))} &mdash; {_e(record.get('company'))}</a></h2>
      <div class="meta-row"><span class="meta">{_e(record.get('location'))}</span><span class="meta">{_e(record.get('posting_date_evidence') or 'date unconfirmed')}</span></div>
      <p><strong>{_e(record.get('failure_category'))}</strong>: {_e(record.get('reason'))}</p>
      <p>{_e(record.get('recommended_manual_check'))}</p>
      <footer><span>{employer}</span><span>Preliminary score: {_e(record.get('preliminary_resume_fit_score') if record.get('preliminary_resume_fit_score') is not None else 'not scored')}</span><span>Not eligible for Agent B or C</span></footer>
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
    manual_records: list[dict[str, Any]] | None = None,
) -> None:
    """Write an interactive, offline HTML shortlist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    strong_count = sum(float(record["final_score"]) >= threshold for record in records)
    companies = len({record["company"].casefold() for record in records})
    cards = "\n".join(_card(record) for record in records)
    manual_records = list(manual_records or [])
    manual_cards = "\n".join(_manual_card(record) for record in manual_records)
    generated = utc_now()
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<style>
:root{{--ink:#17212b;--muted:#647184;--paper:#f3f6f8;--card:#fff;--navy:#15324a;--teal:#168478;--gold:#cc8b19;--red:#b64c4c;--line:#dce4e8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 Inter,Segoe UI,Arial,sans-serif}}a{{color:inherit}}.shell{{max-width:1120px;margin:auto;padding:44px 24px 70px}}header.hero{{background:linear-gradient(130deg,var(--navy),#1c5361);color:#fff;border-radius:22px;padding:34px;box-shadow:0 18px 50px #15324a22}}.hero h1{{margin:0 0 8px;font-size:clamp(30px,5vw,50px);line-height:1.05}}.hero p{{margin:0;max-width:760px;color:#d9e8ec}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:26px}}.stat{{background:#ffffff14;border:1px solid #ffffff22;border-radius:13px;padding:15px}}.stat strong{{display:block;font-size:27px}}.toolbar{{position:sticky;top:0;z-index:4;margin:22px 0;padding:13px;background:#f3f6f8ee;backdrop-filter:blur(10px);display:flex;gap:10px;flex-wrap:wrap}}input,select{{border:1px solid var(--line);background:#fff;border-radius:10px;padding:11px 12px;font:inherit}}input{{flex:1;min-width:220px}}.manual-card{{background:#fff8e8;border:1px solid #ecd9a6;border-left:6px solid var(--gold);border-radius:16px;padding:24px;margin:15px 0;box-shadow:0 8px 28px #1836420c}}.job-card{{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--muted);border-radius:16px;padding:24px;margin:15px 0;box-shadow:0 8px 28px #1836420c}}.job-card.great{{border-left-color:var(--teal)}}.job-card.strong{{border-left-color:#3b8fbb}}.job-card.possible{{border-left-color:var(--gold)}}.job-card.weak{{border-left-color:var(--red)}}.card-head{{display:flex;justify-content:space-between;gap:20px}}h2{{margin:2px 0 8px;font-size:24px;line-height:1.18}}h2 a{{text-decoration:none}}h2 a:hover{{text-decoration:underline}}.eyebrow{{text-transform:uppercase;letter-spacing:.11em;color:var(--muted);font-weight:700;font-size:12px;margin:0}}.score{{min-width:88px;text-align:center;background:var(--paper);border-radius:13px;padding:10px}}.score strong{{display:block;font-size:31px;line-height:1}}.score span{{font-size:12px;text-transform:uppercase;color:var(--muted)}}.meta-row,.chips{{display:flex;gap:7px;flex-wrap:wrap}}.meta,.chip{{background:#edf2f4;border-radius:999px;padding:4px 9px;font-size:12px}}.chip{{background:#e3f3ef;color:#105e56}}.recommendation{{font-weight:700;color:var(--navy)}}.ai{{border-left:3px solid #8a63bb;padding-left:10px;color:#564367}}.intelligence{{background:#fff8e8;border:1px solid #ecd9a6;border-radius:10px;padding:10px 12px;color:#654d17}}.intelligence span{{display:block;color:var(--muted);font-size:12px}}.components{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:17px 0}}.components div{{background:var(--paper);padding:8px;border-radius:8px;display:flex;justify-content:space-between}}.detail-grid{{display:grid;grid-template-columns:1.2fr 1fr;gap:25px}}h3{{font-size:13px;text-transform:uppercase;letter-spacing:.08em;margin:12px 0 8px;color:var(--muted)}}ul{{padding-left:20px}}footer{{border-top:1px solid var(--line);padding-top:12px;margin-top:16px;display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:12px}}.empty{{padding:40px;text-align:center}}@media(max-width:720px){{.stats,.components,.detail-grid{{grid-template-columns:1fr}}.card-head{{align-items:flex-start}}}}
</style></head><body><main class="shell">
<header class="hero"><h1>{_e(title)}</h1><p>{_e(subtitle)}</p><div class="stats"><div class="stat"><strong>{len(records)}</strong>ranked jobs</div><div class="stat"><strong>{strong_count}</strong>strong fits (&ge; {threshold:g})</div><div class="stat"><strong>{companies}</strong>companies</div><div class="stat"><strong>{len(manual_records)}</strong>manual checks</div></div></header>
<div class="toolbar"><input id="search" type="search" placeholder="Filter title, company, or location"><select id="fit"><option value="">All fit levels</option><option>excellent</option><option>strong</option><option>possible</option><option>weak</option></select><select id="mode"><option value="">All work modes</option><option>remote</option><option>hybrid</option><option>onsite</option><option>unknown</option></select><select id="status"><option value="">All statuses</option><option>new</option><option>saved</option><option>ready_to_apply</option><option>applying</option><option>applied</option><option>interviewing</option><option>offer</option><option>accepted</option><option>declined</option><option>rejected</option><option>withdrawn</option><option>closed</option></select></div>
<section id="cards">{cards or '<p class="empty">No scored jobs meet this report cutoff.</p>'}</section>
<section id="manual"><h2>Manual verification queue</h2><p>These leads are visible for human review only and cannot enter Agent B or Agent C.</p>{manual_cards or '<p class="empty">No unresolved relevant leads require manual verification.</p>'}</section>
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
        "posting_trust_score", "posting_trust_level", "posting_flags",
        "repost_appearances", "cross_listing_count",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field, "") for field in fields}
            row["matched_skills"] = "; ".join(record.get("matched_skills", []))
            row["gaps"] = "; ".join(record.get("gaps", []))
            intelligence = record.get("posting_intelligence", {}) or {}
            trust = intelligence.get("trust", {}) or {}
            repost = intelligence.get("repost", {}) or {}
            row["posting_trust_score"] = trust.get("score", "")
            row["posting_trust_level"] = trust.get("level", "")
            row["posting_flags"] = "; ".join(trust.get("flags", []))
            row["repost_appearances"] = (
                repost.get("appearance_count", "") if repost.get("detected") else ""
            )
            row["cross_listing_count"] = len(intelligence.get("cross_listings", []) or [])
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
    manual_records: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    """Export both supported report formats and return their paths."""
    html_path = report_dir / f"{prefix}.html"
    csv_path = report_dir / f"{prefix}.csv"
    export_html(
        records,
        html_path,
        threshold,
        title=title,
        subtitle=subtitle,
        manual_records=manual_records,
    )
    export_csv(records, csv_path)
    return html_path, csv_path

AUDIT_URL_LABELS = {
    "verified_direct_application_link": "Verified direct application link",
    "original_board_link": "Original board link",
    "unverified_link_requiring_manual_review": "Unverified link requiring manual review",
}


def _audit_urls(record: dict[str, Any]) -> str:
    items = []
    for item in record.get("url_evidence", []) or []:
        label = AUDIT_URL_LABELS.get(str(item.get("label")), str(item.get("label") or "Link"))
        items.append(
            f'<li><span class="url-label">{_e(label)}</span> '
            f'<a href="{_e(item.get("url"))}">{_e(item.get("url"))}</a></li>'
        )
    return "".join(items) or "<li>No usable URL was preserved.</li>"


def _audit_card(record: dict[str, Any]) -> str:
    disposition = str(record.get("disposition") or "excluded")
    manual_warning = (
        f'<p class="warning">{_e(record.get("warning"))}</p>'
        if disposition == "manual_verification_required" else ""
    )
    aliases = int(record.get("duplicate_alias_count") or 0)
    score = record.get("preliminary_resume_fit_score")
    score_label = (
        "Final resume fit" if disposition == "verified" else "Preliminary resume fit"
    )
    score_text = f"{float(score):.1f}" if score is not None else "not scored"
    return f"""
    <article class="audit-card { _e(disposition) }" data-disposition="{_e(disposition)}" data-failure="{_e(record.get('failure_category'))}" data-duplicate="{str(aliases > 0).lower()}">
      <p class="eyebrow">{_e(disposition.replace('_', ' ').title())}</p>
      <h2>{_e(record.get('title'))} &mdash; {_e(record.get('company'))}</h2>
      <div class="meta-row"><span class="meta">{_e(record.get('location'))}</span><span class="meta">{_e(record.get('posting_date_evidence') or 'date unconfirmed')}</span></div>
      {manual_warning}
      <p><strong>{_e(record.get('failure_category') or 'passed')}</strong> &mdash; {_e(record.get('reason'))}</p>
      <h3>Source and application links</h3><ul class="urls">{_audit_urls(record)}</ul>
      <footer><code>{_e(record.get('candidate_id'))}</code><span>{aliases} duplicate/alternate source(s)</span><span>{score_label}: {_e(score_text)}</span><span>Agent B eligible: {_e(record.get('eligible_for_agent_b', False))}</span></footer>
    </article>
    """


def export_candidate_audit_html(
    records: list[dict[str, Any]],
    summary: dict[str, int],
    path: Path,
    *,
    title: str = "Current-run candidate report",
    historical_comparison: dict[str, Any] | None = None,
    default_filter: str = "recruiting_leads",
) -> None:
    """Write the complete current-run audit with category and duplicate filters."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cards = "\n".join(_audit_card(record) for record in records)
    recovery_summary = ""
    if "initially_verified" in summary:
        recovery_summary = (
            '<section class="recovery"><h2>Verification recovery</h2><div class="recovery-grid">'
            f'<div><strong>{summary.get("total_source_leads", 0)}</strong><span>source leads</span></div>'
            f'<div><strong>{summary.get("initially_verified", 0)}</strong><span>initially verified</span></div>'
            f'<div><strong>{summary.get("recovery_candidates_attempted", 0)}</strong><span>recovery attempts</span></div>'
            f'<div><strong>{summary.get("candidates_promoted_by_recovery", 0)}</strong><span>promoted</span></div>'
            f'<div><strong>{summary.get("duplicate_browser_requests_avoided", 0)}</strong><span>browser reads avoided</span></div>'
            f'<div><strong>{summary.get("browser_logical_page_reads", 0)}</strong><span>browser reads used</span></div>'
            f'<div><strong>{"yes" if summary.get("browser_budget_exhausted") else "no"}</strong><span>budget exhausted</span></div>'
            '</div></section>'
        )
    history = ""
    if historical_comparison:
        history = (
            '<section class="history"><h2>Historical comparison &mdash; not included in current-run totals.</h2>'
            f'<pre>{_e(json.dumps(historical_comparison, indent=2))}</pre></section>'
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><style>
:root{{--ink:#17212b;--muted:#647184;--paper:#f3f6f8;--card:#fff;--navy:#15324a;--teal:#168478;--gold:#cc8b19;--red:#b64c4c;--line:#dce4e8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Inter,Segoe UI,Arial,sans-serif}}a{{color:#174f75;overflow-wrap:anywhere}}.shell{{max-width:1180px;margin:auto;padding:38px 22px 70px}}.hero{{background:linear-gradient(130deg,var(--navy),#1c5361);color:white;border-radius:20px;padding:30px}}.hero h1{{margin:0 0 8px}}.hero p{{margin:0;color:#d9e8ec}}.stats{{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-top:22px}}.stat{{background:#ffffff14;border:1px solid #ffffff22;border-radius:11px;padding:11px}}.stat strong{{display:block;font-size:24px}}.toolbar{{position:sticky;top:0;z-index:4;display:flex;gap:9px;flex-wrap:wrap;padding:14px 0;background:#f3f6f8ee;backdrop-filter:blur(10px)}}input,select{{border:1px solid var(--line);background:white;border-radius:9px;padding:10px;font:inherit}}input{{flex:1;min-width:230px}}.audit-card{{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--red);border-radius:14px;padding:21px;margin:13px 0}}.audit-card.verified{{border-left-color:var(--teal)}}.audit-card.manual_verification_required{{border-left-color:var(--gold);background:#fffaf0}}.eyebrow{{text-transform:uppercase;letter-spacing:.1em;font-weight:700;font-size:12px;color:var(--muted);margin:0}}h2{{margin:3px 0 8px}}h3{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}.meta-row{{display:flex;gap:7px;flex-wrap:wrap}}.meta,.url-label{{background:#eaf0f3;border-radius:999px;padding:4px 8px;font-size:12px}}.warning{{background:#fff0c7;border:1px solid #e4c264;padding:10px;border-radius:8px;font-weight:700}}.urls{{padding-left:20px}}.urls li{{margin:6px 0}}footer{{border-top:1px solid var(--line);margin-top:14px;padding-top:10px;display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:12px}}.recovery{{background:white;border:1px solid var(--line);border-radius:14px;padding:18px;margin:18px 0}}.recovery h2{{margin-top:0}}.recovery-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:8px}}.recovery-grid div{{background:var(--paper);border-radius:9px;padding:10px}}.recovery-grid strong,.recovery-grid span{{display:block}}.recovery-grid strong{{font-size:21px}}.recovery-grid span{{color:var(--muted);font-size:11px}}.history{{margin-top:30px;border-top:2px solid var(--line)}}pre{{white-space:pre-wrap}}.empty{{padding:35px;text-align:center}}@media(max-width:900px){{.stats{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main class="shell">
<header class="hero"><h1>{_e(title)}</h1><p>Recruiting leads are shown by default. Rejected source noise remains available under All or Excluded for a complete audit; no historical padding is used.</p><div class="stats">
<div class="stat"><strong>{summary.get('current_run_candidates_discovered', 0)}</strong>discovered</div><div class="stat"><strong>{summary.get('unique_current_run_candidates', 0)}</strong>unique</div><div class="stat"><strong>{summary.get('verified', 0)}</strong>verified</div><div class="stat"><strong>{summary.get('manual_verification_required', 0)}</strong>manual</div><div class="stat"><strong>{summary.get('excluded', 0)}</strong>excluded</div><div class="stat"><strong>{summary.get('already_applied', 0)}</strong>already applied</div><div class="stat"><strong>{summary.get('duplicates', 0)}</strong>duplicates</div>
</div></header>
{recovery_summary}<div class="toolbar"><input id="search" type="search" placeholder="Filter title, company, location, or reason"><select id="category"><option value="recruiting_leads"{' selected' if default_filter == 'recruiting_leads' else ''}>Recruiting leads (verified + manual)</option><option value="all"{' selected' if default_filter == 'all' else ''}>All current-run candidates</option><option value="verified"{' selected' if default_filter == 'verified' else ''}>Verified</option><option value="manual_verification_required"{' selected' if default_filter == 'manual_verification_required' else ''}>Manual verification required</option><option value="excluded"{' selected' if default_filter == 'excluded' else ''}>Excluded</option><option value="already_applied"{' selected' if default_filter == 'already_applied' else ''}>Already applied</option><option value="duplicates"{' selected' if default_filter == 'duplicates' else ''}>Duplicates</option></select></div>
<section id="audit">{cards or '<p class="empty">No candidates were discovered in this run.</p>'}</section>{history}
<p>Generated {_e(utc_now())}. Manual-review and excluded candidates cannot enter Agent B or Agent C.</p>
</main><script>
const q=document.querySelector('#search'),category=document.querySelector('#category');
function filter(){{const term=q.value.toLowerCase();document.querySelectorAll('.audit-card').forEach(card=>{{const c=category.value;const isLead=card.dataset.disposition==='verified'||card.dataset.disposition==='manual_verification_required';const categoryMatch=(c==='recruiting_leads'&&isLead)||c==='all'||card.dataset.disposition===c||(c==='already_applied'&&card.dataset.failure==='already_applied')||(c==='duplicates'&&card.dataset.duplicate==='true');card.hidden=!(categoryMatch&&card.textContent.toLowerCase().includes(term));}})}}
[q,category].forEach(el=>el.addEventListener('input',filter));
filter();
</script></body></html>"""
    path.write_text(document, encoding="utf-8", newline="\n")


def export_candidate_audit_csv(records: list[dict[str, Any]], path: Path) -> None:
    """Write every unique current-run candidate with compact labeled URL evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "candidate_id", "disposition", "failure_category", "title", "company",
        "location", "posting_date_evidence", "reason", "preliminary_resume_fit_score",
        "eligible_for_agent_b", "eligible_for_agent_c", "duplicate_alias_count",
        "Verified direct application link", "Original board link",
        "Unverified link requiring manual review",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field, "") for field in fields}
            by_label: dict[str, list[str]] = {}
            for item in record.get("url_evidence", []) or []:
                by_label.setdefault(str(item.get("label")), []).append(str(item.get("url")))
            row["Verified direct application link"] = "; ".join(by_label.get("verified_direct_application_link", []))
            row["Original board link"] = "; ".join(by_label.get("original_board_link", []))
            row["Unverified link requiring manual review"] = "; ".join(by_label.get("unverified_link_requiring_manual_review", []))
            writer.writerow(row)


def export_candidate_audit(
    records: list[dict[str, Any]],
    summary: dict[str, int],
    report_dir: Path,
    *,
    prefix: str = "job_matches",
    title: str = "Current-run candidate report",
    historical_comparison: dict[str, Any] | None = None,
    write_subsets: bool = True,
    default_filter: str = "recruiting_leads",
) -> dict[str, Path]:
    """Export reconciled HTML, CSV, and JSON audits plus manual/excluded subsets."""
    report_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "html": report_dir / f"{prefix}.html",
        "csv": report_dir / f"{prefix}.csv",
        "json": report_dir / f"{prefix}.json",
    }
    export_candidate_audit_html(records, summary, paths["html"], title=title, historical_comparison=historical_comparison, default_filter=default_filter)
    export_candidate_audit_csv(records, paths["csv"])
    paths["json"].write_text(json.dumps({"schema_version": 1, "generated_at": utc_now(), "summary": summary, "records": records, "historical_comparison": historical_comparison or {}}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if historical_comparison:
        history_json = report_dir / f"{prefix}_historical_comparison.json"
        history_html = report_dir / f"{prefix}_historical_comparison.html"
        history_json.write_text(json.dumps(historical_comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        history_html.write_text(
            "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>Historical comparison</title>"
            f"<h1>Historical comparison &mdash; not included in current-run totals.</h1><pre>{_e(json.dumps(historical_comparison, indent=2))}</pre></html>",
            encoding="utf-8",
        )
    if write_subsets:
        for disposition, suffix, subset_title in (
            ("manual_verification_required", "manual_verification", "Manual-verification queue"),
            ("verified", "verified", "Verified Agent B-eligible shortlist"),
            ("excluded", "excluded", "Excluded current-run candidates"),
        ):
            subset = [record for record in records if record.get("disposition") == disposition]
            subset_summary = {
                "current_run_candidates_discovered": len(subset),
                "unique_current_run_candidates": len(subset),
                "verified": sum(item.get("disposition") == "verified" for item in subset),
                "manual_verification_required": sum(item.get("disposition") == "manual_verification_required" for item in subset),
                "excluded": sum(item.get("disposition") == "excluded" for item in subset),
                "already_applied": sum(item.get("failure_category") == "already_applied" for item in subset),
                "duplicates": sum(int(item.get("duplicate_alias_count") or 0) for item in subset),
            }
            export_candidate_audit(subset, subset_summary, report_dir, prefix=f"{prefix}_{suffix}", title=subset_title, write_subsets=False, default_filter=disposition)
    return paths
