"""Run Agent A's JobSpy adapter without the employer-page verification gate."""

from __future__ import annotations

import argparse
import json
import sys

from job_pipeline.integrations.jobspy_source import JobSpySource


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--hours", type=int, default=72)
    parser.add_argument("--results", type=int, default=30)
    parser.add_argument("--site", action="append", required=True)
    parser.add_argument("--country", default="USA")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = JobSpySource()
    jobs = source.search(
        args.query,
        args.location,
        args.hours,
        args.results,
        args.site,
        country=args.country,
        glassdoor_location=args.location,
    )
    payload = {
        "diagnostics": source.last_diagnostics,
        "jobs": [job.to_dict() for job in jobs],
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"output": args.output, "count": len(jobs), "diagnostics": source.last_diagnostics}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
