"""Build the July 22 resume-weighted Recruiting Coordinator search report.

The input records are verified snapshots from employer/job-board pages. The
pipeline's production matching function supplies every fit score so the HTML
report reflects the same rubric used by Agent B.
"""

from __future__ import annotations

import csv
import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_pipeline.jobs import Job
from job_pipeline.matching import score_job
from job_pipeline.resume import resume_context
from job_pipeline.util import stable_id


REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
RESUME_PATH = Path(
    os.environ.get("JOB_PIPELINE_RESUME", str(ROOT / "private" / "resume.docx"))
).expanduser()
PROFILE_PATH = ROOT / "config" / "profile.json"
RUN_DATE = "2026-07-22"
REPORT_STEM = f"recruiting_coordinator_resume_weighted_{RUN_DATE}"
DATA_STEM = f"resume_weighted_matches_{RUN_DATE}"
PAGE_TITLE = "Recruiting roles, weighted against your corrected resume"
PAGE_SUBTITLE = (
    f"Bay Area, San Jose, Sacramento, and Santa Cruz search · generated {RUN_DATE}. "
    "Freshness conflicts are shown instead of being hidden."
)
COVERAGE_NOTE = (
    "The Ivo and Milestone Milpitas / San Jose Recruiting Coordinator postings are marked closed. "
    "Maven Clinic has been restored with its active direct Greenhouse application. No verified, active "
    "exact-title postings inside 24 hours were found in Sacramento or Santa Cruz. Relists remain labeled "
    "with their date conflicts."
)
FRESH_SUMMARY_LABEL = "Fresh / ~24h"
FRESH_FILTER_LABEL = "Fresh / ~24h only"


ROLE_SNAPSHOTS = [
    {
        "title": "Recruiting Coordinator",
        "company": "Ivo",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "Removed from Ivo careers on 2026-07-22",
        "age_hours": 9999,
        "freshness": "closed",
        "freshness_label": "Closed / no longer listed",
        "freshness_note": "The original Ashby URL is stale and Recruiting Coordinator is no longer listed on Ivo's live careers page.",
        "salary": "Not listed",
        "url": "https://www.ivo.ai/careers",
        "source_name": "Ivo careers",
        "action_label": "View Ivo careers ↗",
        "required_years": None,
        "required_skills": [
            "interview scheduling",
            "candidate communication",
            "Ashby ATS",
            "applicant tracking systems",
            "recruiting coordination",
        ],
        "responsibilities": [
            "Schedule interviews across time zones and coordinate candidate logistics.",
            "Manage confirmations, feedback requests, and ATS data hygiene in Ashby.",
            "Screen resumes, source passive talent, and partner with hiring teams.",
            "Improve recruiting processes and deliver a strong candidate experience.",
        ],
        "description": (
            "About the role: coordinate interviews across time zones, candidate logistics, confirmations, "
            "feedback requests, and onsite interviews. Maintain ATS data hygiene in Ashby, screen resumes, "
            "source passive talent, communicate with candidates, partner with recruiters and hiring managers, "
            "and improve recruiting processes. The position is onsite in San Francisco."
        ),
    },
    {
        "title": "Recruiting Coordinator (Contract)",
        "company": "Maven Clinic",
        "location": "Remote, United States (San Francisco hub eligible)",
        "work_mode": "remote",
        "employment_type": "6-month contract",
        "posted_date": "Active application verified 2026-07-22",
        "age_hours": 24,
        "freshness": "fresh",
        "freshness_label": "Active / verified",
        "freshness_note": "Maven's current Greenhouse application form is active and accepting applications.",
        "salary": "$25.00–$37.50/hour",
        "url": "https://job-boards.greenhouse.io/mavenclinic/jobs/8561262002",
        "source_name": "Maven Clinic / Greenhouse",
        "required_years": 1,
        "required_skills": [
            "high-volume scheduling",
            "candidate communication",
            "Greenhouse ATS",
            "ModernLoop",
            "candidate experience",
        ],
        "responsibilities": [
            "Coordinate more than 75 interviews per week and candidate travel logistics.",
            "Communicate with candidates and partner with recruiters and hiring managers.",
            "Maintain Greenhouse and ModernLoop workflows and improve recruiting processes.",
        ],
        "description": (
            "Responsibilities include scheduling 75+ interviews weekly, candidate travel and logistics, "
            "candidate communication, recruiter and hiring manager partnership, Greenhouse and ModernLoop "
            "administration, and recruiting process improvement. Qualifications include at least one year of "
            "recruiting coordination experience. This is a remote United States six-month contract."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "SiTime",
        "location": "Santa Clara, CA",
        "work_mode": "onsite",
        "employment_type": "Contract",
        "posted_date": "Board relist: 3h; original listing: about 2 weeks",
        "age_hours": 3,
        "freshness": "repost",
        "freshness_label": "Repost — verify date",
        "freshness_note": "Built In showed three hours, while the corresponding LinkedIn listing showed about two weeks.",
        "salary": "$52/hour",
        "url": "https://builtin.com/job/recruiting-coordinator/9582147",
        "source_name": "Built In / SiTime",
        "required_years": 2,
        "required_skills": [
            "interview scheduling",
            "candidate experience",
            "candidate communication",
            "recruiting coordination",
        ],
        "responsibilities": [
            "Schedule interviews across time zones and coordinate onsite candidates.",
            "Support talent acquisition operations and protect confidential information.",
        ],
        "description": (
            "Responsibilities include coordinating interviews across time zones, onsite candidate logistics, "
            "candidate communication, talent acquisition coordination, and confidential records. Qualifications "
            "include two to four years of recruiting coordination experience. The role is onsite five days per week."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Milestone Technologies",
        "location": "Milpitas / San Jose, CA",
        "work_mode": "onsite",
        "employment_type": "6-month W-2 contract",
        "posted_date": "Closed as of 2026-07-22",
        "age_hours": 9999,
        "freshness": "closed",
        "freshness_label": "Closed / no longer listed",
        "freshness_note": "The Milpitas / San Jose Recruiting Coordinator application is closed; the former Dice listing is no longer usable.",
        "salary": "$28–$33/hour",
        "url": "https://milestone.tech/careers/",
        "source_name": "Milestone Technologies careers",
        "action_label": "View Milestone careers ↗",
        "required_years": 1,
        "required_skills": [
            "interview scheduling",
            "candidate communication",
            "applicant tracking systems",
            "offer letters",
            "background checks",
            "Microsoft Excel",
        ],
        "responsibilities": [
            "Manage more than 20 concurrent interview schedules and candidate communications.",
            "Prepare offer letters and coordinate background checks and preboarding.",
            "Maintain recruiting metrics and ATS records; SAP SuccessFactors is preferred.",
        ],
        "description": (
            "Responsibilities include 20+ concurrent interview schedules, candidate communication, ATS records, "
            "offer letters, background checks, preboarding, and recruiting metrics. Outlook, calendar management, "
            "and Excel are used; SAP SuccessFactors is preferred. Qualifications include one to three years in "
            "recruiting coordination, talent acquisition operations, or HR coordination."
        ),
    },
    {
        "title": "Talent Acquisition Coordinator",
        "company": "Milestone Technologies",
        "location": "Foster City, CA",
        "work_mode": "hybrid",
        "employment_type": "Contract",
        "posted_date": "Company result: 1h; detailed listing: about 3 days",
        "age_hours": 1,
        "freshness": "repost",
        "freshness_label": "Repost — verify date",
        "freshness_note": "A company result showed one hour, but the detailed listing showed about three days.",
        "salary": "$25–$30/hour",
        "url": "https://www.linkedin.com/jobs/view/talent-acquisition-coordinator-at-milestone-technologies-inc-4427772181",
        "source_name": "Milestone Technologies / LinkedIn",
        "required_years": None,
        "required_skills": [
            "interview scheduling",
            "candidate communication",
            "candidate experience",
            "onboarding",
        ],
        "responsibilities": [
            "Coordinate phone, Zoom, and onsite interviews and manage candidate logistics.",
            "Collect feedback, arrange debriefs and NDAs, and support onboarding documentation.",
        ],
        "description": (
            "Responsibilities include phone, Zoom, and onsite interview scheduling, candidate communication and "
            "logistics, feedback collection, debriefs, NDAs, onboarding, and employment documentation. The contract "
            "role requires onsite work two to four days weekly in Foster City."
        ),
    },
]


def make_job(item: dict) -> Job:
    """Convert a verified report snapshot to the pipeline's canonical Job."""
    return Job(
        id=stable_id(item["url"]),
        url=item["url"],
        title=item["title"],
        company=item["company"],
        location=item["location"],
        work_mode=item["work_mode"],
        employment_type=item["employment_type"],
        posted_date=item["posted_date"],
        salary=item["salary"],
        description=item["description"],
        source=item["source_name"],
        required_years=item["required_years"],
        required_skills=item["required_skills"],
        responsibilities=item["responsibilities"],
    )


def fit_class(score: float) -> str:
    if score >= 82:
        return "excellent"
    if score >= 72:
        return "strong"
    if score >= 60:
        return "possible"
    return "weak"


def render_list(values: list[str], empty: str = "None identified") -> str:
    if not values:
        return f'<li class="muted">{html.escape(empty)}</li>'
    return "".join(f"<li>{html.escape(value)}</li>" for value in values)


def build() -> tuple[Path, Path, Path]:
    """Score the verified roles and write HTML, JSON, and CSV artifacts."""
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if not RESUME_PATH.is_file():
        raise FileNotFoundError(
            "Resume not found. Set JOB_PIPELINE_RESUME to the local .docx resume path."
        )
    resume_text = resume_context(RESUME_PATH)
    required_terms = [
        term.strip().casefold()
        for term in os.environ.get("JOB_PIPELINE_RESUME_REQUIRED_TERMS", "").split(",")
        if term.strip()
    ]
    missing_terms = [term for term in required_terms if term not in resume_text.casefold()]
    if missing_terms:
        raise RuntimeError(
            "The selected resume is missing required terms: " + ", ".join(missing_terms)
        )

    scored = []
    for item in ROLE_SNAPSHOTS:
        job = make_job(item)
        match = score_job(job, profile, resume_text)
        scored.append({"job": job, "match": match, "snapshot": item})
    scored.sort(
        key=lambda row: (
            {"fresh": 0, "repost": 1, "closed": 2}.get(row["snapshot"]["freshness"], 3),
            -row["match"].final_score,
            row["snapshot"]["age_hours"],
        )
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / f"{DATA_STEM}.json"
    csv_path = REPORT_DIR / f"{REPORT_STEM}.csv"
    html_path = REPORT_DIR / f"{REPORT_STEM}.html"

    export = []
    for row in scored:
        record = row["job"].to_dict()
        record["match"] = row["match"].to_dict()
        record["freshness"] = {
            "status": row["snapshot"]["freshness"],
            "label": row["snapshot"]["freshness_label"],
            "note": row["snapshot"]["freshness_note"],
        }
        export.append(record)
    json_path.write_text(json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "score", "fit", "freshness", "company", "title", "location", "work_mode",
            "posted", "salary", "matched_resume_skills", "resume_evidence", "gaps", "apply_url"
        ])
        for row in scored:
            job, match, snap = row["job"], row["match"], row["snapshot"]
            writer.writerow([
                match.final_score, match.fit_label, snap["freshness_label"], job.company, job.title,
                job.location, job.work_mode, job.posted_date, job.salary,
                "; ".join(match.matched_skills), "; ".join(match.matched_evidence),
                "; ".join(match.gaps), job.url,
            ])

    cards = []
    for index, row in enumerate(scored, start=1):
        job, match, snap = row["job"], row["match"], row["snapshot"]
        freshness_priority = {"fresh": 2, "repost": 1, "closed": 0}.get(snap["freshness"], 0)
        components = "".join(
            f'<div class="metric"><span>{html.escape(name.title())}</span><b>{value:.0f}</b>'
            f'<div class="bar"><i style="width:{value}%"></i></div></div>'
            for name, value in match.components.items()
        )
        cards.append(f"""
        <article class="job-card" data-score="{match.final_score}" data-fit="{fit_class(match.final_score)}"
          data-fresh="{snap['freshness']}" data-mode="{job.work_mode}" data-age="{snap['age_hours']}"
          data-priority="{freshness_priority}" data-company="{html.escape(job.company.casefold())}"
          data-text="{html.escape((job.title + ' ' + job.company + ' ' + job.location + ' ' + ' '.join(match.matched_skills)).casefold())}">
          <div class="rank">#{index}</div>
          <div class="card-top">
            <div>
              <div class="eyebrow">{html.escape(job.company)}</div>
              <h2>{html.escape(job.title)}</h2>
              <p class="meta">{html.escape(job.location)} · {html.escape(job.work_mode.title())} · {html.escape(job.employment_type)}</p>
            </div>
            <div class="score {fit_class(match.final_score)}"><strong>{match.final_score:.0f}</strong><span>resume fit</span></div>
          </div>
          <div class="badges">
            <span class="badge {snap['freshness']}">{html.escape(snap['freshness_label'])}</span>
            <span class="badge neutral">{html.escape(job.posted_date)}</span>
            <span class="badge neutral">{html.escape(job.salary)}</span>
          </div>
          <p class="freshness-note">{html.escape(snap['freshness_note'])}</p>
          <div class="component-grid">{components}</div>
          <details open>
            <summary>Why your resume matches</summary>
            <div class="detail-grid">
              <section><h3>Matched resume skills</h3><ul>{render_list(match.matched_skills)}</ul></section>
              <section><h3>Evidence used</h3><ul>{render_list(match.matched_evidence)}</ul></section>
              <section><h3>Verify or address</h3><ul>{render_list(match.gaps)}</ul></section>
              <section><h3>Role responsibilities</h3><ul>{render_list(job.responsibilities)}</ul></section>
            </div>
          </details>
          <div class="actions">
            <a class="primary" href="{html.escape(job.url)}" target="_blank" rel="noopener">{html.escape(snap.get('action_label', 'View / apply ↗'))}</a>
            <span>{html.escape(match.recommendation)}</span>
          </div>
        </article>""")

    weights = profile["scoring"]["weights"]
    weight_text = " · ".join(f"{name.title()} {int(weight * 100)}%" for name, weight in weights.items())
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(PAGE_TITLE)} — {RUN_DATE}</title>
<style>
:root{{--ink:#14213d;--muted:#5d6879;--paper:#fff;--bg:#f3f6f8;--line:#dce3e8;--accent:#005f73;--gold:#ee9b00;--green:#18794e;--red:#b42318}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(145deg,#edf4f3,#f7f2e8 52%,#eef2f6);color:var(--ink);font:15px/1.48 Inter,Segoe UI,sans-serif}}
header{{background:#0a3d44;color:white;padding:48px max(24px,calc((100vw - 1180px)/2));border-bottom:6px solid #e9b949}}
header h1{{font:700 clamp(30px,5vw,56px)/1.05 Georgia,serif;margin:8px 0 14px;max-width:900px}} header p{{max-width:850px;color:#dceeed;margin:0}}
.kicker{{text-transform:uppercase;letter-spacing:.16em;font-weight:800;color:#f3cc72;font-size:12px}}
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;max-width:1180px;margin:-24px auto 22px;padding:0 24px;position:relative}}
.summary div{{background:white;padding:18px;border:1px solid var(--line);box-shadow:0 8px 25px #16343e17}} .summary b{{display:block;font-size:26px;color:#0a5964}} .summary span{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}}
main{{max-width:1180px;margin:auto;padding:0 24px 70px}} .notice{{background:#fff8e7;border-left:5px solid var(--gold);padding:16px 18px;margin-bottom:18px}}
.resume-box{{background:#e5f2f1;border:1px solid #b7d8d3;padding:18px;margin-bottom:18px}} .resume-box b{{color:#075863}}
.controls{{position:sticky;top:0;z-index:10;background:#f4f7f6eF;backdrop-filter:blur(10px);display:grid;grid-template-columns:2fr repeat(4,1fr);gap:10px;padding:14px 0}}
input,select{{width:100%;border:1px solid #b9c5ca;background:white;padding:11px 12px;color:var(--ink);font:inherit}}
.job-card{{position:relative;background:var(--paper);border:1px solid var(--line);padding:24px;margin:16px 0;box-shadow:0 7px 25px #23333d0f}} .job-card[hidden]{{display:none}}
.rank{{position:absolute;right:14px;top:10px;color:#a3adb5;font:700 12px/1 monospace}} .card-top{{display:flex;justify-content:space-between;gap:18px}}
.eyebrow{{color:var(--accent);font-weight:800;text-transform:uppercase;letter-spacing:.11em;font-size:12px}} h2{{font:700 27px/1.15 Georgia,serif;margin:4px 0 8px}} .meta,.freshness-note{{color:var(--muted);margin:0}}
.score{{width:92px;height:92px;border-radius:50%;display:grid;place-content:center;text-align:center;flex:0 0 auto;border:7px solid}} .score strong{{font-size:29px;line-height:1}} .score span{{font-size:10px;text-transform:uppercase}}
.score.excellent{{color:#11633c;border-color:#8fd3ae;background:#effaf3}} .score.strong{{color:#075d6b;border-color:#7fcbd3;background:#eef9fa}} .score.possible{{color:#9b5d00;border-color:#f4ca79;background:#fff8e8}} .score.weak{{color:#9f2820;border-color:#f0aaa5;background:#fff1f0}}
.badges{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 8px}} .badge{{border-radius:99px;padding:5px 10px;font-size:12px;font-weight:700}} .badge.fresh{{background:#dcf4e6;color:#11633c}} .badge.repost{{background:#fff0ce;color:#8b5800}} .badge.closed{{background:#fee4e2;color:#9f2820}} .badge.neutral{{background:#eef1f3;color:#4d5967}}
.component-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:20px 0}} .metric{{background:#f7f9fa;padding:10px}} .metric span{{display:block;color:var(--muted);font-size:11px}} .metric b{{font-size:18px}} .bar{{height:4px;background:#dce4e7;margin-top:6px}} .bar i{{display:block;height:100%;background:#087987}}
details{{border-top:1px solid var(--line);padding-top:14px}} summary{{cursor:pointer;font-weight:800;color:#075863}} .detail-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px 28px}} h3{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin:17px 0 5px}} ul{{padding-left:19px;margin:5px 0}} li{{margin:4px 0}} .muted{{color:var(--muted)}}
.actions{{display:flex;align-items:center;gap:16px;border-top:1px solid var(--line);padding-top:16px;margin-top:17px;color:var(--muted)}} .primary{{background:#075f69;color:white;text-decoration:none;padding:11px 15px;font-weight:800}} .primary:hover{{background:#003f46}}
.empty{{display:none;background:white;padding:30px;text-align:center;color:var(--muted)}} footer{{color:var(--muted);font-size:12px;margin-top:30px}}
@media(max-width:800px){{.summary{{grid-template-columns:1fr 1fr}}.controls{{grid-template-columns:1fr 1fr}}.controls input{{grid-column:1/-1}}.card-top{{align-items:flex-start}}.component-grid{{grid-template-columns:1fr 1fr}}.detail-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header><div class="kicker">Agent A discovery · Agent B verification</div><h1>{html.escape(PAGE_TITLE)}</h1><p>{html.escape(PAGE_SUBTITLE)}</p></header>
<div class="summary"><div><b id="visibleCount">{len(scored)}</b><span>Visible matches</span></div><div><b>{sum(1 for row in scored if row['snapshot']['freshness']=='fresh')}</b><span>{html.escape(FRESH_SUMMARY_LABEL)}</span></div><div><b>{sum(1 for row in scored if row['snapshot']['freshness']=='repost')}</b><span>Reposts to verify</span></div><div><b>{max(row['match'].final_score for row in scored):.0f}</b><span>Highest resume fit</span></div></div>
<main>
  <div class="notice"><b>Coverage note:</b> {html.escape(COVERAGE_NOTE)}</div>
  <div class="resume-box"><b>Resume source:</b> {html.escape(RESUME_PATH.name)} · loaded locally and not copied into the report.<br><b>Score weights:</b> {html.escape(weight_text)}. Scores use only documented resume/profile evidence; no credential is inferred.</div>
  <div class="controls">
    <input id="search" type="search" placeholder="Search company, title, location, or matched skill…">
    <select id="fit"><option value="all">All fit levels</option><option value="excellent">Excellent (82+)</option><option value="strong">Strong (72–81)</option><option value="possible">Possible (60–71)</option></select>
    <select id="fresh"><option value="all">All posting dates</option><option value="fresh">{html.escape(FRESH_FILTER_LABEL)}</option><option value="repost">Reposts to verify</option><option value="closed">Closed / removed</option></select>
    <select id="mode"><option value="all">All work modes</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">Onsite</option></select>
    <select id="sort"><option value="priority">Sort: fresh first + fit</option><option value="score">Sort: best fit</option><option value="freshest">Sort: newest claim</option><option value="company">Sort: company</option></select>
  </div>
  <section id="jobs">{''.join(cards)}</section><div id="empty" class="empty">No roles match the selected filters.</div>
  <footer>Search snapshot {RUN_DATE}. Job availability, salary, work mode, and posting age can change; verify them on the linked employer or job-board page before applying. Previously applied companies were excluded from this search.</footer>
</main>
<script>
const jobs=document.getElementById('jobs'), cards=[...document.querySelectorAll('.job-card')];
const controls=['search','fit','fresh','mode','sort'].map(id=>document.getElementById(id));
function refresh(){{
 const q=controls[0].value.trim().toLowerCase(), fit=controls[1].value, fresh=controls[2].value, mode=controls[3].value;
 cards.forEach(c=>c.hidden=!((!q||c.dataset.text.includes(q))&&(fit==='all'||c.dataset.fit===fit)&&(fresh==='all'||c.dataset.fresh===fresh)&&(mode==='all'||c.dataset.mode===mode)));
 const visible=cards.filter(c=>!c.hidden); document.getElementById('visibleCount').textContent=visible.length; document.getElementById('empty').style.display=visible.length?'none':'block';
 const sort=controls[4].value; cards.sort((a,b)=>sort==='company'?a.dataset.company.localeCompare(b.dataset.company):sort==='freshest'?Number(a.dataset.age)-Number(b.dataset.age):sort==='score'?Number(b.dataset.score)-Number(a.dataset.score):(Number(b.dataset.priority)-Number(a.dataset.priority)||Number(b.dataset.score)-Number(a.dataset.score))); cards.forEach(c=>jobs.appendChild(c)); visible.forEach((c,i)=>c.querySelector('.rank').textContent='#'+(i+1));
}}
controls.forEach(c=>c.addEventListener(c.id==='search'?'input':'change',refresh)); refresh();
</script>
</body></html>"""
    html_path.write_text(html_doc, encoding="utf-8")
    return html_path, csv_path, json_path


if __name__ == "__main__":
    for output in build():
        print(output)
