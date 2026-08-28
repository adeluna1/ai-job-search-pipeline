import { useCallback, useEffect, useState } from 'react';
import { Power, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { api, isDesktop } from '@/lib/api';
import type { AgentsResult } from '@/lib/api';

export default function Agents() {
  const [result, setResult] = useState<AgentsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [engineBusy, setEngineBusy] = useState(false);
  const [engineMsg, setEngineMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setResult(await api.agentsList());
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const startEngine = async () => {
    setEngineBusy(true);
    setEngineMsg('launching…');
    try {
      const res = await api.servicesStart('paperclip');
      if (res.paperclip?.up) {
        setEngineMsg(null);
        await load(); // auto-refresh agents once healthy
      } else {
        setEngineMsg(res.paperclip?.error ? `failed: ${res.paperclip.error}` : 'failed to start');
      }
    } finally {
      setEngineBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-100">Agents</h1>
        <Button
          variant="outline"
          className="border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-white"
          onClick={load}
          disabled={busy}
        >
          <RefreshCw className={`mr-2 h-4 w-4 ${busy ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {result && !result.online && (
        <Card className="border-amber-800/50 bg-amber-950/20">
          <CardContent className="flex flex-col items-start gap-4 pt-6">
            <p className="text-sm text-amber-300">
              {result.message || 'Paperclip offline — start it with scripts/paperclip-start-local.ps1'}
            </p>
            <div className="flex items-center gap-3">
              <Button
                onClick={startEngine}
                disabled={engineBusy || !isDesktop}
                className="bg-cyan-500 text-slate-950 hover:bg-cyan-400"
              >
                <Power className="mr-2 h-4 w-4" />
                {engineBusy ? 'Starting…' : 'Engine Start'}
              </Button>
              {engineMsg && (
                <span className={`text-xs ${engineMsg.startsWith('failed') ? 'text-rose-400' : 'text-slate-400'}`}>
                  {engineMsg}
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {result?.online && (
        <p className="text-sm text-slate-400">
          company: <span className="text-slate-200">{result.company ?? '—'}</span>
          {result.message && <span className="ml-2 text-amber-300">{result.message}</span>}
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(result?.agents ?? []).map((a, i) => (
          <Card key={a.id ?? i} className="border-slate-800 bg-slate-900/60">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm text-slate-200">{a.name ?? 'agent'}</CardTitle>
                <div className="flex gap-2">
                  {a.paused && (
                    <Badge className="bg-amber-500/15 text-amber-300 hover:bg-amber-500/15">
                      paused
                    </Badge>
                  )}
                  <Badge className="bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/15">
                    {a.status ?? 'unknown'}
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-slate-400">adapter: {a.adapterType ?? '—'}</p>
            </CardContent>
          </Card>
        ))}
        {result?.online && result.agents.length === 0 && (
          <p className="text-sm text-slate-500">no agents returned</p>
        )}
      </div>
    </div>
  );
}
