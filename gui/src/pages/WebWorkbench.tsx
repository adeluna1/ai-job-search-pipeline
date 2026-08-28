import { useEffect, useMemo, useState } from 'react';
import { Braces, Play, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';
import type { ToolContract, WorkflowInput } from '@/lib/api';

export default function WebWorkbench() {
  const [tools, setTools] = useState<ToolContract[]>([]);
  const [toolName, setToolName] = useState('web.only_cli.sites');
  const [argumentsText, setArgumentsText] = useState('{"args":[]}');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    void api.toolsList().then((items) => {
      if (!active) return;
      setTools(items);
      const preferred = items.find((item) => item.name === 'web.only_cli.sites') || items[0];
      if (preferred) setToolName(preferred.name);
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Tools could not load.');
    });
    return () => { active = false; };
  }, []);

  const selected = useMemo(
    () => tools.find((item) => item.name === toolName),
    [toolName, tools],
  );

  const definition = (): WorkflowInput => ({
    name: 'interactive-web-workbench',
    steps: [{
      id: 'command',
      tool: toolName,
      arguments: JSON.parse(argumentsText) as Record<string, unknown>,
      max_attempts: 1,
    }],
  });

  const execute = async (dryRun: boolean) => {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const workflow = definition();
      setResult(dryRun ? await api.workflowsDryRun(workflow) : await api.workflowsRun(workflow));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Workflow could not run.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mx-auto max-w-[1500px] space-y-7">
      <header className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-[-0.03em] text-slate-50">Web workbench</h1>
        <p className="mt-2 text-sm leading-6 text-slate-400">
          Inspect the typed agent tool surface, dry-run workflows, and execute bounded only-cli or pipeline operations.
        </p>
      </header>

      <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <div className="rounded-lg border border-slate-800 bg-slate-900/45 p-5">
          <label className="block text-xs font-medium text-slate-400">
            Tool
            <select
              value={toolName}
              onChange={(event) => setToolName(event.target.value)}
              className="mt-2 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-cyan-400"
            >
              {tools.map((tool) => <option key={tool.name}>{tool.name}</option>)}
            </select>
          </label>
          <p className="mt-3 min-h-12 text-xs leading-5 text-slate-500">
            {selected?.description || 'Waiting for the local tool catalog.'}
          </p>
          <div className="mt-3 flex items-center gap-2 text-[10px] uppercase tracking-[0.1em] text-slate-500">
            <ShieldCheck className="h-3.5 w-3.5 text-cyan-300" />
            Policy: {selected?.policy?.replaceAll('_', ' ') || 'unknown'}
          </div>
          <label className="mt-5 block text-xs font-medium text-slate-400">
            Arguments, JSON
            <textarea
              value={argumentsText}
              onChange={(event) => setArgumentsText(event.target.value)}
              spellCheck={false}
              className="mt-2 min-h-44 w-full resize-y rounded-md border border-slate-700 bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-200 outline-none focus:ring-2 focus:ring-cyan-400"
            />
          </label>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <button
              type="button"
              disabled={busy || !selected}
              onClick={() => void execute(true)}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:opacity-40"
            >
              <Braces className="h-4 w-4" />
              Dry run
            </button>
            <button
              type="button"
              disabled={busy || !selected}
              onClick={() => void execute(false)}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-cyan-300 text-sm font-semibold text-cyan-950 hover:bg-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-100 disabled:opacity-40"
            >
              <Play className="h-4 w-4" />
              Execute
            </button>
          </div>
        </div>

        <div className="min-w-0 overflow-hidden rounded-lg border border-slate-800 bg-slate-950/65">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <span className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Structured result</span>
            <span className="font-mono text-[10px] text-slate-600">content remains local</span>
          </div>
          {error ? (
            <div role="alert" className="m-4 rounded-md border border-rose-900 bg-rose-950/35 px-4 py-3 text-sm text-rose-200">
              {error}
            </div>
          ) : (
            <pre className="min-h-[480px] overflow-auto p-5 font-mono text-xs leading-6 text-slate-300">
              {result ? JSON.stringify(result, null, 2) : 'Run a dry check or execute a typed workflow to inspect its result.'}
            </pre>
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-800">
        <div className="grid grid-cols-[minmax(220px,1fr)_130px_minmax(260px,2fr)] bg-slate-900 px-4 py-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
          <span>Tool</span><span>Policy</span><span>Purpose</span>
        </div>
        {tools.map((tool) => (
          <div key={tool.name} className="grid grid-cols-[minmax(220px,1fr)_130px_minmax(260px,2fr)] border-t border-slate-800 px-4 py-3 text-xs">
            <code className="truncate font-mono text-cyan-200">{tool.name}</code>
            <span className="text-slate-500">{tool.policy.replaceAll('_', ' ')}</span>
            <span className="text-slate-400">{tool.description}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
