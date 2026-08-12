import { useEffect, useRef, useState } from 'react';
import { ExternalLink, Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api, isDesktop } from '@/lib/api';
import type { JobRow, SearchLogPayload } from '@/lib/api';

export default function Search() {
  const [query, setQuery] = useState('');
  const [locationsText, setLocationsText] = useState('');
  const [freshHours, setFreshHours] = useState<24 | 72 | 168 | 336>(168);
  const [concurrency, setConcurrency] = useState(4);
  const [resumePath, setResumePath] = useState('');
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const [rows, setRows] = useState<JobRow[] | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const off = api.onSearchLog((p: SearchLogPayload) => {
      setLog((prev) => [...prev.slice(-2000), p.line]);
    });
    return off;
  }, []);

  useEffect(() => {
    api.appInfo().then((info) => {
      setQuery(info.defaultQuery);
      setLocationsText(info.defaultLocations.join('; '));
      setResumePath(info.defaultResumePath);
    });
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const run = async () => {
    setRunning(true);
    setLog([]);
    setExitCode(null);
    setRows(null);
    try {
      const locations = locationsText
        .split(/[\n;]+/)
        .map((value) => value.trim())
        .filter(Boolean);
      const res = await api.searchSpawn({
        query, locations, freshHours, resultsWanted: 10, concurrency, resumePath,
      });
      if (res.output && res.code !== 0) setLog((prev) => [...prev, res.output]);
      setExitCode(res.code);
      const jobs = await api.jobsRead();
      setRows(jobs.rows);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-100">Search</h1>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-slate-200">Agent A — find &amp; triage</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
            <div className="space-y-1 xl:col-span-2">
              <Label className="text-slate-300">Query</Label>
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="border-slate-700 bg-slate-950 text-slate-200"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-slate-300">Locations (semicolon separated)</Label>
              <Input
                value={locationsText}
                onChange={(e) => setLocationsText(e.target.value)}
                className="border-slate-700 bg-slate-950 text-slate-200"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-slate-300">Freshness window</Label>
              <select
                value={freshHours}
                onChange={(e) => setFreshHours(Number(e.target.value) as 24 | 72 | 168 | 336)}
                className="border-slate-700 bg-slate-950 text-slate-200"
              >
                <option value={24}>Last 24 hours</option>
                <option value={72}>Last 3 days</option>
                <option value={168}>Last 7 days (daily recommended)</option>
                <option value={336}>Last 14 days (weekly expansion)</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label className="text-slate-300">Maximum results</Label>
                <Input
                  type="text"
                  value="10 (hard cap)"
                  disabled
                  className="border-slate-700 bg-slate-950 text-slate-200"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-slate-300">Concurrency</Label>
                <Input
                  type="number"
                  value={concurrency}
                  onChange={(e) => setConcurrency(Number(e.target.value))}
                  className="border-slate-700 bg-slate-950 text-slate-200"
                />
              </div>
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-slate-300">Corrected resume used for scoring</Label>
            <div className="flex gap-2">
              <Input
                value={resumePath}
                readOnly
                placeholder="Choose the corrected .docx resume"
                className="border-slate-700 bg-slate-950 text-slate-200"
              />
              <Button
                type="button"
                variant="outline"
                onClick={async () => {
                  const picked = await api.resumePick();
                  if (!picked.canceled) setResumePath(picked.path);
                }}
                disabled={!isDesktop}
              >
                Browse
              </Button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button
              onClick={run}
              disabled={running || !isDesktop || !resumePath}
              className="bg-cyan-500 text-slate-950 hover:bg-cyan-400"
            >
              <Play className="mr-2 h-4 w-4" />
              {running ? 'Running…' : 'Run search'}
            </Button>
            {!isDesktop && (
              <span className="text-xs text-slate-500">
                desktop-only: launch via Electron to run the pipeline
              </span>
            )}
            {exitCode !== null && (
              <span className={`text-xs ${exitCode === 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                exit code {exitCode}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-slate-200">Live log</CardTitle>
        </CardHeader>
        <CardContent>
          <div
            ref={logRef}
            className="h-64 overflow-auto rounded-md bg-slate-950 p-4 font-mono text-xs text-slate-300"
          >
            {log.length === 0 ? (
              <span className="text-slate-600">output will stream here…</span>
            ) : (
              log.map((l, i) => <div key={i}>{l}</div>)
            )}
          </div>
        </CardContent>
      </Card>

      {rows && (
        <Card className="border-slate-800 bg-slate-900/60">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-slate-200">Results ({rows.length})</CardTitle>
            <Button
              variant="outline"
              className="border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-white"
              onClick={() => api.reportOpen()}
              disabled={!isDesktop}
            >
              <ExternalLink className="mr-2 h-4 w-4" />
              Open HTML report
            </Button>
          </CardHeader>
          <CardContent>
            <div className="overflow-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-xs uppercase text-slate-500">
                    <th className="p-2">Score</th>
                    <th className="p-2">Fit</th>
                    <th className="p-2">Title</th>
                    <th className="p-2">Company</th>
                    <th className="p-2">Location</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className="border-b border-slate-800/50 text-slate-300">
                      <td className="p-2 font-semibold text-cyan-300">{r.score}</td>
                      <td className="p-2">{r.fit_label || r.fit}</td>
                      <td className="p-2">{r.title}</td>
                      <td className="p-2">{r.company}</td>
                      <td className="p-2">{r.location}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
