"""Build an interactive dashboard from durable application and lifecycle records."""

from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .application_history import job_identity_from_fields, load_applied_registry
from .lifecycle import SEARCH_SUPPRESSION_STATES
from .storage import JobStore
from .util import utc_now, write_json


STATUS_LABELS = {
    "applying": "Applying",
    "applied": "Applied",
    "interviewing": "Interviewing",
    "offer": "Offer",
    "accepted": "Accepted",
    "declined": "Declined",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
    "closed": "Closed",
}
OUTCOME_LABELS = {
    "interview": "Interview",
    "denied": "Denied",
    "not_selected": "Did not get job",
}
ACTIVE_STATES = {"applying", "applied", "interviewing", "offer"}
CLOSED_STATES = {"accepted", "declined", "rejected", "withdrawn", "closed"}


def _clean_status(value: Any) -> tuple[str, bool]:
    """Return a dashboard-safe status and whether it was inferred from a legacy row."""
    status = str(value or "").strip().casefold()
    if status not in SEARCH_SUPPRESSION_STATES:
        return "applied", True
    return status, False


def _first(values: Any) -> str:
    """Return the first non-empty string in a sequence-like value."""
    if isinstance(values, list):
        return next((str(value).strip() for value in values if str(value).strip()), "")
    return ""


def collect_application_records(
    store: JobStore,
    registry_path: Path,
) -> list[dict[str, Any]]:
    """Merge the alias-aware applied registry with detailed SQLite lifecycle rows."""
    merged: dict[str, dict[str, Any]] = {}
    registry = load_applied_registry(registry_path)
    for source in registry["jobs"]:
        company = str(source.get("company") or "").strip()
        title = str(source.get("title") or "").strip()
        if not company or not title:
            continue
        identity = str(source.get("identity_key") or job_identity_from_fields(company, title))
        status, inferred = _clean_status(source.get("status"))
        urls = sorted({str(url).strip() for url in source.get("urls", []) if str(url).strip()})
        merged[identity] = {
            "identity_key": identity,
            "job_id": _first(source.get("job_ids")),
            "company": company,
            "title": title,
            "status": status,
            "status_label": STATUS_LABELS[status],
            "status_inferred": inferred,
            "outcome_flag": str(source.get("outcome_flag") or ""),
            "outcome_label": OUTCOME_LABELS.get(
                str(source.get("outcome_flag") or ""), ""
            ),
            "applied_at": str(source.get("applied_at") or ""),
            "updated_at": str(source.get("status_updated_at") or source.get("applied_at") or ""),
            "location": "",
            "work_mode": "",
            "employment_type": "",
            "salary": "",
            "source": ", ".join(sorted({str(item) for item in source.get("sources", []) if item})),
            "fit_score": "",
            "notes": str(source.get("notes") or ""),
            "url": urls[0] if urls else "",
            "urls": urls,
        }

    rows = store.connection.execute(
        """
        SELECT j.id, j.url, j.title, j.company, j.location, j.work_mode,
               j.employment_type, j.salary, j.source, a.status, a.notes,
               a.updated_at, m.final_score,
               (SELECT MIN(e.created_at) FROM application_events e
                WHERE e.job_id=j.id AND e.to_status='applied') AS applied_event_at
        FROM jobs j
        JOIN applications a ON a.job_id=j.id
        LEFT JOIN matches m ON m.job_id=j.id
        ORDER BY a.updated_at DESC
        """
    ).fetchall()
    for row in rows:
        item = dict(row)
        identity = job_identity_from_fields(item["company"], item["title"])
        status = str(item["status"] or "").casefold()
        if identity not in merged and status not in SEARCH_SUPPRESSION_STATES:
            continue
        record = merged.get(identity)
        if record is None:
            normalized, inferred = _clean_status(status)
            record = {
                "identity_key": identity,
                "job_id": item["id"],
                "company": item["company"],
                "title": item["title"],
                "status": normalized,
                "status_label": STATUS_LABELS[normalized],
                "status_inferred": inferred,
                "outcome_flag": "",
                "outcome_label": "",
                "applied_at": str(item.get("applied_event_at") or item["updated_at"] or ""),
                "updated_at": str(item["updated_at"] or ""),
                "location": "",
                "work_mode": "",
                "employment_type": "",
                "salary": "",
                "source": "",
                "fit_score": "",
                "notes": "",
                "url": "",
                "urls": [],
            }
            merged[identity] = record

        if status in SEARCH_SUPPRESSION_STATES:
            record["status"] = status
            record["status_label"] = STATUS_LABELS[status]
            record["status_inferred"] = False
        record["job_id"] = item["id"]
        record["location"] = item["location"]
        record["work_mode"] = item["work_mode"]
        record["employment_type"] = item["employment_type"]
        record["salary"] = item["salary"]
        record["source"] = item["source"] or record["source"]
        record["fit_score"] = (
            round(float(item["final_score"]), 1) if item["final_score"] is not None else ""
        )
        record["notes"] = item["notes"] or record["notes"]
        record["updated_at"] = item["updated_at"] or record["updated_at"]
        record["applied_at"] = (
            item.get("applied_event_at") or record["applied_at"] or item["updated_at"]
        )
        urls = sorted({*record["urls"], str(item["url"] or "").strip()} - {""})
        record["urls"] = urls
        record["url"] = urls[0] if urls else ""

    return sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("applied_at") or item.get("updated_at") or ""),
            item["company"].casefold(),
            item["title"].casefold(),
        ),
        reverse=True,
    )


def application_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate compact dashboard totals from normalized application records."""
    statuses = Counter(record["status"] for record in records)
    return {
        "total": len(records),
        "active": sum(
            1
            for record in records
            if record["status"] in ACTIVE_STATES and not record["status_inferred"]
        ),
        "interviewing": statuses["interviewing"],
        "offers": statuses["offer"] + statuses["accepted"],
        "closed": sum(
            1
            for record in records
            if record["status"] in CLOSED_STATES and not record["status_inferred"]
        ),
        "status_not_recorded": sum(bool(record["status_inferred"]) for record in records),
        "companies": len({record["company"].casefold() for record in records}),
        "status_counts": dict(sorted(statuses.items())),
    }


def _display_date(value: Any) -> str:
    """Return the date portion of an ISO timestamp without inventing one."""
    text = str(value or "")
    return text[:10] if len(text) >= 10 else text


def export_application_csv(records: list[dict[str, Any]], path: Path) -> None:
    """Write a spreadsheet-friendly application tracker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "company", "title", "status", "status_label", "status_inferred", "outcome_flag", "outcome_label",
        "applied_at", "updated_at", "location", "work_mode", "employment_type",
        "salary", "fit_score", "source", "notes", "url", "job_id",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})


def export_application_html(
    records: list[dict[str, Any]],
    summary: dict[str, Any],
    path: Path,
) -> None:
    """Write a self-contained, interactive application dashboard."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for record in records:
        status_note = (
            record["outcome_label"]
            or (
                "Applied - status not recorded"
                if record["status_inferred"]
                else record["status_label"]
            )
        )
        link = (
            '<a href="{}" target="_blank" rel="noopener noreferrer">Open role</a>'.format(
                html.escape(record["url"], quote=True)
            )
            if record["url"]
            else '<span class="muted">No saved link</span>'
        )
        rows.append(
            f"""<tr data-status="{html.escape(record["status"])}">
<td><strong>{html.escape(record["company"])}</strong><small>{html.escape(record["source"])}</small></td>
<td>{html.escape(record["title"])}</td>
<td><span class="pill s-{html.escape(record["status"])}">{html.escape(status_note)}</span></td>
<td>{html.escape(_display_date(record["applied_at"]))}</td>
<td>{html.escape(record["location"] or "Not recorded")}</td>
<td>{html.escape(str(record["fit_score"]))}</td>
<td>{html.escape(record["notes"])}</td><td>{link}</td></tr>"""
        )
    payload = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    generated = utc_now()
    options = "".join(
        f'<option value="{key}">{html.escape(label)}</option>'
        for key, label in STATUS_LABELS.items()
    )
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Application dashboard</title><style>
:root{{--navy:#15324a;--teal:#168478;--paper:#f3f6f8;--card:#fff;--ink:#17212b;--muted:#687687;--line:#dce4e8;--gold:#cc8b19}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 Inter,Segoe UI,Arial,sans-serif}}
main{{max-width:1400px;margin:auto;padding:34px 22px 70px}}header{{background:linear-gradient(130deg,var(--navy),#176775);color:#fff;border-radius:20px;padding:30px}}
h1{{font-size:clamp(30px,5vw,48px);margin:0 0 7px}}header p{{margin:0;color:#d8ebed}}.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:24px}}
.stat{{background:#ffffff16;border:1px solid #ffffff25;border-radius:12px;padding:13px}}.stat b{{display:block;font-size:25px}}.stat span{{font-size:12px}}
.notice{{margin:18px 0;background:#fff5d9;border:1px solid #ecd390;border-radius:12px;padding:13px;color:#624b15}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}}input,select{{border:1px solid var(--line);border-radius:10px;padding:11px;background:#fff;font:inherit}}
input{{flex:1;min-width:260px}}button{{border:0;border-radius:10px;padding:11px 15px;background:var(--navy);color:#fff;cursor:pointer}}
.table-wrap{{overflow:auto;background:#fff;border:1px solid var(--line);border-radius:15px}}table{{width:100%;border-collapse:collapse;min-width:1050px}}
th,td{{padding:13px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}th{{position:sticky;top:0;background:#eaf0f3;font-size:11px;text-transform:uppercase;letter-spacing:.06em}}
small{{display:block;color:var(--muted)}}.pill{{display:inline-block;border-radius:999px;padding:4px 9px;background:#e8edf0;white-space:nowrap}}.s-interviewing,.s-offer,.s-accepted{{background:#dff3e9;color:#106044}}
.s-rejected,.s-declined,.s-withdrawn,.s-closed{{background:#f4e5e3;color:#8c302c}}.s-applied,.s-applying{{background:#e0edf6;color:#205c82}}
a{{color:#08766e;font-weight:700}}.muted,.foot{{color:var(--muted)}}.foot{{margin-top:14px}}tr[hidden]{{display:none}}
@media(max-width:900px){{.stats{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main><header><h1>Applications dashboard</h1>
<p>Every role retained by the pipeline's applied-role registry and lifecycle tracker.</p>
<div class="stats"><div class="stat"><b>{summary["total"]}</b><span>Total applications</span></div>
<div class="stat"><b>{summary["active"]}</b><span>Active</span></div><div class="stat"><b>{summary["interviewing"]}</b><span>Interviewing</span></div>
<div class="stat"><b>{summary["offers"]}</b><span>Offers / accepted</span></div><div class="stat"><b>{summary["closed"]}</b><span>Closed outcomes</span></div>
<div class="stat"><b>{summary["companies"]}</b><span>Companies</span></div></div></header>
<div class="notice"><strong>{summary["status_not_recorded"]} legacy records</strong> do not yet include an outcome. They are displayed as applied with ?Status not recorded? and can be updated as responses arrive.</div>
<div class="toolbar"><input id="q" type="search" placeholder="Search company, role, location, or notes">
<select id="status"><option value="">All statuses</option>{options}</select>
<button id="reset">Reset filters</button></div>
<div class="table-wrap"><table><thead><tr><th>Company</th><th>Role</th><th>Status</th><th>Applied</th><th>Location</th><th>Fit</th><th>Notes</th><th>Link</th></tr></thead>
<tbody id="rows">{''.join(rows) if rows else '<tr><td colspan="8">No applications are tracked yet.</td></tr>'}</tbody></table></div>
<p id="visible" class="foot"></p><p class="foot">Generated {html.escape(generated)}. Stored locally; no resume or contact details are included.</p>
<script id="application-data" type="application/json">{payload}</script><script>
const q=document.querySelector('#q'),s=document.querySelector('#status'),rows=[...document.querySelectorAll('#rows tr[data-status]')],visible=document.querySelector('#visible');
function apply(){{const term=q.value.toLowerCase();let n=0;for(const row of rows){{const show=(!term||row.textContent.toLowerCase().includes(term))&&(!s.value||row.dataset.status===s.value);row.hidden=!show;if(show)n++}}visible.textContent=n+' of '+rows.length+' applications shown';}}
q.addEventListener('input',apply);s.addEventListener('change',apply);document.querySelector('#reset').addEventListener('click',()=>{{q.value='';s.value='';apply()}});apply();
</script></main></body></html>"""
    path.write_text(document, encoding="utf-8", newline="\n")


def export_application_dashboard(
    store: JobStore,
    registry_path: Path,
    report_dir: Path,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    """Generate HTML, CSV, and JSON application dashboard artifacts."""
    records = collect_application_records(store, registry_path)
    summary = application_summary(records)
    html_path = report_dir / "applications_dashboard.html"
    csv_path = report_dir / "applications_dashboard.csv"
    json_path = report_dir / "applications_dashboard.json"
    export_application_html(records, summary, html_path)
    export_application_csv(records, csv_path)
    write_json(json_path, {
        "schema_version": 1,
        "generated_at": utc_now(),
        "summary": summary,
        "applications": records,
    })
    return html_path, csv_path, json_path, summary
