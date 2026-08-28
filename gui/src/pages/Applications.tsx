import { useEffect, useMemo, useState } from 'react';
import { FileText, RefreshCw, RotateCcw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import type {
  ApplicationDashboardResult,
  ApplicationOutcomeFlag,
  ApplicationRecord,
} from '@/lib/api';

const EMPTY_RESULT: ApplicationDashboardResult = {
  exists: false,
  summary: {},
  applications: [],
};

const OUTCOMES: Array<{ value: ApplicationOutcomeFlag; label: string }> = [
  { value: 'interview', label: 'Interview' },
  { value: 'denied', label: 'Denied' },
  { value: 'not_selected', label: 'Not selected' },
];

function shortDate(value: string) {
  return value ? value.slice(0, 10) : 'Not recorded';
}

export default function Applications() {
  const [result, setResult] = useState<ApplicationDashboardResult>(EMPTY_RESULT);
  const [loading, setLoading] = useState(true);
  const [busyIdentity, setBusyIdentity] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [notice, setNotice] = useState<{ tone: 'good' | 'bad'; text: string } | null>(null);
  const [undoIdentity, setUndoIdentity] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const next = await api.applicationsRead();
      setResult(next);
      setNotice(next.error ? { tone: 'bad', text: next.error } : null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    void api.applicationsRead().then((next) => {
      if (!active) return;
      setResult(next);
      setNotice(next.error ? { tone: 'bad', text: next.error } : null);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const refresh = async () => {
    setNotice(null);
    setLoading(true);
    try {
      const response = await api.applicationsRefresh();
      if (response.code !== 0) {
        setNotice({ tone: 'bad', text: response.output || 'Application refresh failed.' });
      }
      await load();
    } finally {
      setLoading(false);
    }
  };

  const setOutcome = async (item: ApplicationRecord, flag: ApplicationOutcomeFlag) => {
    const label = OUTCOMES.find((option) => option.value === flag)?.label || flag;
    if (!window.confirm(`Set ${item.company}, ${item.title} to ${label}?`)) return;
    setBusyIdentity(item.identity_key);
    setNotice(null);
    try {
      const response = await api.applicationsFlag(item.identity_key, flag);
      if (response.code !== 0) {
        setNotice({ tone: 'bad', text: response.output || 'The outcome could not be saved.' });
        return;
      }
      setUndoIdentity(item.identity_key);
      setNotice({ tone: 'good', text: `${item.company} is now marked ${label}.` });
      await load();
    } finally {
      setBusyIdentity('');
    }
  };

  const undo = async () => {
    if (!undoIdentity) return;
    setBusyIdentity(undoIdentity);
    try {
      const response = await api.applicationsUndo(undoIdentity);
      if (response.code !== 0) {
        setNotice({ tone: 'bad', text: response.output || 'The last change could not be undone.' });
        return;
      }
      setUndoIdentity('');
      setNotice({ tone: 'good', text: 'The previous application state was restored.' });
      await load();
    } finally {
      setBusyIdentity('');
    }
  };

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return result.applications.filter((item) => {
      const statusMatches = !status || item.status === status;
      const text = [item.company, item.title, item.location, item.source, item.notes]
        .join(' ')
        .toLowerCase();
      return statusMatches && (!needle || text.includes(needle));
    });
  }, [query, result.applications, status]);

  const knownStatuses = useMemo(
    () => [...new Set(result.applications.map((item) => item.status).filter(Boolean))].sort(),
    [result.applications],
  );
  const summary = result.summary;
  const measures = [
    ['Tracked', summary.total ?? 0],
    ['Active', summary.active ?? 0],
    ['Interviewing', summary.interviewing ?? 0],
    ['Offers', summary.offers ?? 0],
    ['Closed', summary.closed ?? 0],
  ];

  return (
    <section className="mx-auto max-w-[1500px] space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-[-0.03em] text-slate-50">Applications</h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            One durable record of drafts, submitted roles, interviews, and closed outcomes.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={!result.exists}
            onClick={() => void api.applicationsReportOpen()}
            className="border-slate-700 bg-slate-900 text-slate-200 hover:bg-slate-800"
          >
            <FileText className="mr-2 h-4 w-4" />
            Open report
          </Button>
          <Button
            disabled={loading}
            onClick={() => void refresh()}
            className="bg-cyan-400 text-slate-950 hover:bg-cyan-300"
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh data
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-2 border-y border-slate-800 md:grid-cols-5">
        {measures.map(([label, value], index) => (
          <div
            key={label}
            className={`px-4 py-5 ${index > 0 ? 'border-l border-slate-800' : ''}`}
          >
            <div className="font-mono text-2xl tabular-nums text-slate-100">{value}</div>
            <div className="mt-1 text-xs font-medium uppercase tracking-[0.12em] text-slate-500">
              {label}
            </div>
          </div>
        ))}
      </div>

      {notice && (
        <div
          role={notice.tone === 'bad' ? 'alert' : 'status'}
          className={`flex flex-wrap items-center gap-3 rounded-md border px-4 py-3 text-sm ${
            notice.tone === 'bad'
              ? 'border-rose-800 bg-rose-950/40 text-rose-200'
              : 'border-emerald-800 bg-emerald-950/35 text-emerald-200'
          }`}
        >
          <span>{notice.text}</span>
          {notice.tone === 'good' && undoIdentity && (
            <Button
              size="sm"
              variant="outline"
              disabled={busyIdentity === undoIdentity}
              onClick={() => void undo()}
              className="border-emerald-700 bg-transparent text-emerald-100 hover:bg-emerald-900"
            >
              <RotateCcw className="mr-2 h-3.5 w-3.5" />
              Undo change
            </Button>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-64 flex-1">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-500" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search company, role, location, or note"
            className="border-slate-700 bg-slate-900 pl-9 text-slate-100 placeholder:text-slate-500"
          />
        </div>
        <select
          aria-label="Filter by application status"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-10 rounded-md border border-slate-700 bg-slate-900 px-3 text-sm text-slate-200 outline-none focus:ring-2 focus:ring-cyan-400"
        >
          <option value="">All statuses</option>
          {knownStatuses.map((value) => (
            <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>
          ))}
        </select>
      </div>

      <div className="overflow-hidden rounded-md border border-slate-800 bg-slate-900/45">
        <div className="overflow-auto">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="bg-slate-900 text-xs uppercase tracking-[0.1em] text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Company and role</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Outcome</th>
                <th className="px-4 py-3 font-medium">Applied</th>
                <th className="px-4 py-3 font-medium">Location</th>
                <th className="px-4 py-3 font-medium">Fit</th>
                <th className="px-4 py-3 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.identity_key} className="border-t border-slate-800 text-slate-300">
                  <td className="max-w-80 px-4 py-4">
                    <div className="font-medium text-slate-100">{item.company}</div>
                    <div className="mt-1 text-slate-400">{item.title}</div>
                  </td>
                  <td className="px-4 py-4">
                    <span className="rounded-full bg-cyan-400/10 px-2.5 py-1 text-xs text-cyan-200">
                      {item.status_inferred ? 'Applied, outcome not recorded' : item.status_label}
                    </span>
                  </td>
                  <td className="px-4 py-4">
                    <select
                      aria-label={`Set outcome for ${item.company}, ${item.title}`}
                      value={item.outcome_flag}
                      disabled={busyIdentity === item.identity_key}
                      onChange={(event) => {
                        const flag = event.target.value as ApplicationOutcomeFlag;
                        if (flag) void setOutcome(item, flag);
                      }}
                      className="h-9 min-w-36 rounded-md border border-slate-700 bg-slate-950 px-2 text-xs text-slate-200 outline-none focus:ring-2 focus:ring-cyan-400 disabled:opacity-50"
                    >
                      <option value="">Set outcome</option>
                      {OUTCOMES.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-4 font-mono text-xs tabular-nums text-slate-400">
                    {shortDate(item.applied_at)}
                  </td>
                  <td className="max-w-52 px-4 py-4 text-slate-400">{item.location || 'Not recorded'}</td>
                  <td className="px-4 py-4 font-mono tabular-nums text-cyan-200">{item.fit_score}</td>
                  <td className="max-w-40 truncate px-4 py-4 text-xs text-slate-500" title={item.source}>
                    {item.source || 'Unknown'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!loading && filtered.length === 0 && (
          <div className="border-t border-slate-800 px-6 py-14 text-center">
            <p className="font-medium text-slate-200">
              {result.applications.length === 0 ? 'No applications recorded yet.' : 'No applications match these filters.'}
            </p>
            <p className="mt-2 text-sm text-slate-500">
              {result.applications.length === 0
                ? 'Approved application drafts and submitted roles will appear here.'
                : 'Clear a filter or try a broader search.'}
            </p>
          </div>
        )}
        {loading && (
          <div className="border-t border-slate-800 px-6 py-14 text-center text-sm text-slate-400">
            Loading application history...
          </div>
        )}
      </div>
    </section>
  );
}
