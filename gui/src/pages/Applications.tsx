import { useEffect, useMemo, useState } from 'react';
import { ExternalLink, RefreshCw, RotateCcw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import type { ApplicationDashboardResult, ApplicationOutcomeFlag, ApplicationRecord } from '@/lib/api';

const EMPTY_SUMMARY = {
  total: 0,
  active: 0,
  interviewing: 0,
  offers: 0,
  closed: 0,
  status_not_recorded: 0,
  companies: 0,
  status_counts: {},
};

const STATUS_ORDER = [
  'applying', 'applied', 'interviewing', 'offer', 'accepted',
  'declined', 'rejected', 'withdrawn', 'closed',
];

function dateOnly(value: string) {
  return value ? value.slice(0, 10) : 'Not recorded';
}

export default function Applications() {
  const [result, setResult] = useState<ApplicationDashboardResult>({
    exists: false,
    summary: EMPTY_SUMMARY,
    applications: [],
  });
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [messageIsError, setMessageIsError] = useState(false);
  const [updatingIdentity, setUpdatingIdentity] = useState('');
  const [lastChange, setLastChange] = useState<{
    identityKey: string;
    company: string;
    title: string;
  } | null>(null);

  const load = async () => {
    setResult(await api.applicationsRead());
  };

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const refresh = async () => {
    setBusy(true);
    setMessage('');
    try {
      const response = await api.applicationsRefresh();
      if (response.code !== 0) setMessage(response.output || 'Dashboard refresh failed.');
      await load();
    } finally {
      setBusy(false);
    }
  };

  const flagApplication = async (
    item: ApplicationRecord,
    flag: ApplicationOutcomeFlag,
  ) => {
    const label = flag === 'interview'
      ? 'Interview'
      : flag === 'denied'
        ? 'Denied'
        : "Didn't get job";
    const confirmed = window.confirm(
      `Change ${item.company} — ${item.title} to “${label}”? You can undo this change afterward.`,
    );
    if (!confirmed) return;

    setUpdatingIdentity(item.identity_key);
    setMessage('');
    setMessageIsError(false);
    try {
      const response = await api.applicationsFlag(item.identity_key, flag);
      if (response.code !== 0) {
        setMessageIsError(true);
        setMessage(response.output || 'Could not save the outcome.');
        return;
      }
      setLastChange({
        identityKey: item.identity_key,
        company: item.company,
        title: item.title,
      });
      setMessage(`${item.company} was changed to ${label}.`);
      await load();
    } finally {
      setUpdatingIdentity('');
    }
  };

  const undoLastChange = async () => {
    if (!lastChange) return;
    setUpdatingIdentity(lastChange.identityKey);
    setMessage('');
    setMessageIsError(false);
    try {
      const response = await api.applicationsUndo(lastChange.identityKey);
      if (response.code !== 0) {
        setMessageIsError(true);
        setMessage(response.output || 'Could not undo the outcome change.');
        return;
      }
      setMessage(`Restored the previous status for ${lastChange.company}.`);
      setLastChange(null);
      await load();
    } finally {
      setUpdatingIdentity('');
    }
  };

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    return result.applications.filter((item) => {
      const matchesStatus = !status || item.status === status;
      const haystack = [
        item.company, item.title, item.location, item.notes, item.source,
      ].join(' ').toLowerCase();
      return matchesStatus && (!term || haystack.includes(term));
    });
  }, [result.applications, query, status]);

  const summary = result.summary || EMPTY_SUMMARY;
  const stats = [
    ['Total', summary.total],
    ['Active', summary.active],
    ['Interviewing', summary.interviewing],
    ['Offers / accepted', summary.offers],
    ['Closed', summary.closed],
    ['Companies', summary.companies],
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Applications</h1>
          <p className="text-sm text-slate-400">
            Durable applied-role history plus current lifecycle outcomes.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            className="border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700"
            onClick={() => void api.applicationsReportOpen()}
            disabled={!result.exists}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Interactive report
          </Button>
          <Button
            onClick={refresh}
            disabled={busy}
            className="bg-cyan-500 text-slate-950 hover:bg-cyan-400"
          >
            <RefreshCw className={'mr-2 h-4 w-4 ' + (busy ? 'animate-spin' : '')} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {stats.map(([label, value]) => (
          <Card key={String(label)} className="border-slate-800 bg-slate-900/60">
            <CardContent className="p-4">
              <div className="text-2xl font-bold text-cyan-300">{value}</div>
              <div className="text-xs text-slate-400">{label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {summary.status_not_recorded > 0 && (
        <div className="rounded-lg border border-amber-700/50 bg-amber-950/30 p-3 text-sm text-amber-200">
          {summary.status_not_recorded} legacy applications have no outcome recorded yet.
          They remain labeled applied until their statuses are updated.
        </div>
      )}
      {message && (
        <div className={`flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm ${
          messageIsError
            ? 'border-rose-800/60 bg-rose-950/30 text-rose-300'
            : 'border-emerald-800/60 bg-emerald-950/30 text-emerald-300'
        }`}>
          <span>{message}</span>
          {!messageIsError && lastChange && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={updatingIdentity === lastChange.identityKey}
              onClick={() => void undoLastChange()}
              className="border-emerald-700 bg-transparent text-emerald-200 hover:bg-emerald-900/50"
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              Undo
            </Button>
          )}
        </div>
      )}

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="space-y-3">
          <CardTitle className="text-slate-200">
            {filtered.length} of {summary.total} applications
          </CardTitle>
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-64 flex-1">
              <Search className="absolute left-3 top-3 h-4 w-4 text-slate-500" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search company, role, location, or notes"
                className="border-slate-700 bg-slate-950 pl-9 text-slate-100"
              />
            </div>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-200"
            >
              <option value="">All statuses</option>
              {STATUS_ORDER.map((value) => (
                <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>
              ))}
            </select>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-auto">
            <table className="w-full min-w-[950px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase text-slate-500">
                  <th className="p-2">Company</th>
                  <th className="p-2">Role</th>
                  <th className="p-2">Status</th>
                  <th className="p-2">Outcome</th>
                  <th className="p-2">Applied</th>
                  <th className="p-2">Location</th>
                  <th className="p-2">Fit</th>
                  <th className="p-2">Notes</th>
                  <th className="p-2">Link</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item: ApplicationRecord) => (
                  <tr key={item.identity_key} className="border-b border-slate-800/50 text-slate-300">
                    <td className="max-w-48 p-2">
                      <strong className="block text-slate-200">{item.company}</strong>
                      <span className="text-xs text-slate-500">{item.source}</span>
                    </td>
                    <td className="max-w-64 p-2">{item.title}</td>
                    <td className="p-2">
                      <span className="rounded-full bg-cyan-500/15 px-2 py-1 text-xs text-cyan-300">
                        {item.status_inferred ? 'applied - status not recorded' : item.status_label}
                      </span>
                    </td>
                    <td className="p-2">
                      <select
                        value={item.outcome_flag}
                        disabled={updatingIdentity === item.identity_key}
                        onChange={(event) => {
                          const flag = event.target.value as ApplicationOutcomeFlag;
                          if (flag) void flagApplication(item, flag);
                        }}
                        className="min-w-36 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                        aria-label={`Flag outcome for ${item.company} ${item.title}`}
                      >
                        <option value="">Flag outcome...</option>
                        <option value="interview">Interview</option>
                        <option value="denied">Denied</option>
                        <option value="not_selected">Didn't get job</option>
                      </select>
                    </td>
                    <td className="p-2">{dateOnly(item.applied_at)}</td>
                    <td className="max-w-48 p-2">{item.location || 'Not recorded'}</td>
                    <td className="p-2 text-cyan-300">{item.fit_score}</td>
                    <td className="max-w-52 truncate p-2" title={item.notes}>{item.notes}</td>
                    <td className="p-2">
                      {item.url && (
                        <button
                          className="text-cyan-400 hover:underline"
                          onClick={() => void api.externalOpen(item.url)}
                        >
                          open
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr><td colSpan={9} className="p-8 text-center text-slate-500">
                    No applications match these filters.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
