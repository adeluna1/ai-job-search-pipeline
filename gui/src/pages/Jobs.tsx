import { useEffect, useMemo, useState } from 'react';
import { ArrowUpDown } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { api } from '@/lib/api';
import type { JobRow } from '@/lib/api';

const COLUMNS = [
  { key: 'score', label: 'Score' },
  { key: 'fit_label', label: 'Fit' },
  { key: 'title', label: 'Title' },
  { key: 'company', label: 'Company' },
  { key: 'location', label: 'Location' },
  { key: 'work_mode', label: 'Mode' },
  { key: 'salary', label: 'Salary' },
  { key: 'matched_skills', label: 'Matched skills' },
  { key: 'gaps', label: 'Gaps' },
  { key: 'url', label: 'Link' },
];

type SortDir = 'asc' | 'desc';

export default function Jobs() {
  const [rows, setRows] = useState<JobRow[]>([]);
  const [exists, setExists] = useState(true);
  const [sortKey, setSortKey] = useState<string>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  useEffect(() => {
    api.jobsRead().then((res) => {
      setRows(res.rows);
      setExists(res.exists);
    });
  }, []);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey] ?? '';
      const bv = b[sortKey] ?? '';
      const an = Number(av);
      const bn = Number(bv);
      let cmp: number;
      if (!Number.isNaN(an) && !Number.isNaN(bn) && av !== '' && bv !== '') {
        cmp = an - bn;
      } else {
        cmp = String(av).localeCompare(String(bv));
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const toggleSort = (key: string) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'score' ? 'desc' : 'asc');
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-100">Jobs</h1>
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-slate-200">
            reports/job_matches.csv {!exists && '(not found yet — run a search)'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase text-slate-500">
                  {COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      className="cursor-pointer select-none p-2 hover:text-cyan-300"
                      onClick={() => toggleSort(c.key)}
                    >
                      <span className="inline-flex items-center gap-1">
                        {c.label}
                        <ArrowUpDown className="h-3 w-3" />
                        {sortKey === c.key && (sortDir === 'asc' ? '↑' : '↓')}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r, i) => (
                  <tr key={i} className="border-b border-slate-800/50 text-slate-300">
                    {COLUMNS.map((c) => (
                      <td key={c.key} className="max-w-56 truncate p-2" title={r[c.key]}>
                        {c.key === 'url' ? (
                          r.url ? (
                            <a
                              href={r.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-cyan-400 hover:underline"
                            >
                              open
                            </a>
                          ) : (
                            ''
                          )
                        ) : c.key === 'score' ? (
                          <span className="font-semibold text-cyan-300">{r[c.key]}</span>
                        ) : (
                          r[c.key]
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
                {sorted.length === 0 && (
                  <tr>
                    <td colSpan={COLUMNS.length} className="p-6 text-center text-slate-500">
                      no rows
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
