import { useEffect, useState } from 'react';
import { CalendarClock, Clock3, Play, Plus, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';
import type { ScheduleRecord, WorkflowInput } from '@/lib/api';

function nextRun(value: string) {
  if (!value) return 'Not scheduled';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export default function Automations() {
  const [schedules, setSchedules] = useState<ScheduleRecord[]>([]);
  const [name, setName] = useState('Recruiting discovery and scoring');
  const [interval, setIntervalMinutes] = useState(360);
  const [maxJobs, setMaxJobs] = useState(250);
  const [minScore, setMinScore] = useState(72);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const load = async () => setSchedules(await api.schedulesList());

  useEffect(() => {
    let active = true;
    void api.schedulesList().then((items) => {
      if (active) setSchedules(items);
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Schedules could not load.');
    });
    return () => { active = false; };
  }, []);

  const create = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    const workflow: WorkflowInput = {
      name: 'scheduled-recruiting-hunt',
      steps: [{
        id: 'discover_score_report',
        tool: 'jobs.pipeline.run',
        arguments: {
          max_jobs: maxJobs,
          concurrency: 4,
          min_score: minScore,
        },
        max_attempts: 2,
      }],
    };
    try {
      await api.schedulesCreate({
        name,
        workflow,
        recurrence: {
          kind: 'interval',
          interval_minutes: interval,
          local_time: '',
          timezone_name: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
        },
      });
      await load();
      setNotice('Automation saved. It can discover, score, store, and report without submitting applications.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Automation could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (item: ScheduleRecord) => {
    setBusy(true);
    try {
      await api.schedulesToggle(item.id, !item.enabled);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const runDue = async () => {
    setBusy(true);
    setError('');
    try {
      const results = await api.schedulesRunDue();
      setNotice(results.length ? `Completed ${results.length} due automation run.` : 'No automation is due right now.');
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Due automations could not run.');
    } finally {
      setBusy(false);
    }
  };

  const installWake = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await api.schedulesInstallWake();
      if (response.code !== 0) throw new Error(response.output || 'Background wake installation failed.');
      setNotice('Background wake installed. Due schedules can now recover after app restarts.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Background wake installation failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mx-auto max-w-[1500px] space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-[-0.03em] text-slate-50">Automations</h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Restart-safe scheduled discovery, scoring, data processing, and local draft work.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void installWake()}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-4 text-sm text-slate-200 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:opacity-40"
          >
            <Clock3 className="h-4 w-4" />
            Install background wake
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void runDue()}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-4 text-sm text-slate-200 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:opacity-40"
          >
            <Play className="h-4 w-4" />
            Run due now
          </button>
        </div>
      </header>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/35">
          <div className="grid grid-cols-[minmax(0,1fr)_160px_100px] border-b border-slate-800 px-4 py-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
            <span>Workflow</span>
            <span>Next run</span>
            <span>Status</span>
          </div>
          {schedules.map((item) => (
            <div key={item.id} className="grid grid-cols-[minmax(0,1fr)_160px_100px] items-center border-b border-slate-800/80 px-4 py-4 last:border-b-0">
              <div className="min-w-0 pr-4">
                <div className="truncate text-sm font-medium text-slate-100">{item.name}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {item.recurrence.kind === 'interval'
                    ? `Every ${item.recurrence.interval_minutes} minutes`
                    : `Daily at ${item.recurrence.local_time}`}
                </div>
              </div>
              <div className="font-mono text-xs tabular-nums text-slate-400">{nextRun(item.next_run_at)}</div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void toggle(item)}
                aria-pressed={item.enabled}
                className={`rounded-full border px-2.5 py-1 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-cyan-400 ${
                  item.enabled
                    ? 'border-emerald-800 bg-emerald-950/40 text-emerald-300'
                    : 'border-slate-700 text-slate-500'
                }`}
              >
                {item.enabled ? 'Enabled' : 'Paused'}
              </button>
            </div>
          ))}
          {schedules.length === 0 && (
            <div className="px-6 py-16 text-center">
              <CalendarClock className="mx-auto h-7 w-7 text-cyan-300" />
              <p className="mt-4 text-sm font-medium text-slate-200">No scheduled hunts yet.</p>
              <p className="mt-2 text-sm text-slate-500">Create one from the controls beside this list.</p>
            </div>
          )}
        </div>

        <div className="self-start rounded-lg border border-slate-800 bg-slate-900/45 p-5">
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-slate-100">Schedule a job hunt</h2>
          <p className="mt-2 text-xs leading-5 text-slate-500">
            Each run processes a large bounded batch. Missed intervals coalesce into one recovery run.
          </p>
          <div className="mt-5 space-y-4">
            <label className="block text-xs font-medium text-slate-400">
              Name
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-2 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-cyan-400"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs font-medium text-slate-400">
                Every, minutes
                <input
                  type="number"
                  min={5}
                  max={10080}
                  value={interval}
                  onChange={(event) => setIntervalMinutes(Number(event.target.value))}
                  className="mt-2 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 font-mono text-sm text-slate-100 outline-none focus:ring-2 focus:ring-cyan-400"
                />
              </label>
              <label className="block text-xs font-medium text-slate-400">
                Jobs per run
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={maxJobs}
                  onChange={(event) => setMaxJobs(Number(event.target.value))}
                  className="mt-2 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 font-mono text-sm text-slate-100 outline-none focus:ring-2 focus:ring-cyan-400"
                />
              </label>
            </div>
            <label className="block text-xs font-medium text-slate-400">
              Minimum fit score
              <input
                type="number"
                min={0}
                max={100}
                value={minScore}
                onChange={(event) => setMinScore(Number(event.target.value))}
                className="mt-2 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 font-mono text-sm text-slate-100 outline-none focus:ring-2 focus:ring-cyan-400"
              />
            </label>
            <button
              type="button"
              disabled={busy || !name.trim()}
              onClick={() => void create()}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-cyan-300 text-sm font-semibold text-cyan-950 hover:bg-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-100 disabled:opacity-40"
            >
              <Plus className="h-4 w-4" />
              Create automation
            </button>
          </div>
          <div className="mt-5 flex gap-2 border-t border-slate-800 pt-4 text-xs leading-5 text-slate-500">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" />
            Submissions and employer messages cannot be placed in unattended schedules. Draft preparation remains local and review-required.
          </div>
        </div>
      </div>

      {(notice || error) && (
        <div role={error ? 'alert' : 'status'} className={`rounded-md border px-4 py-3 text-sm ${
          error
            ? 'border-rose-900 bg-rose-950/35 text-rose-200'
            : 'border-emerald-900 bg-emerald-950/30 text-emerald-200'
        }`}>
          {error || notice}
        </div>
      )}
    </section>
  );
}
