import { useCallback, useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { api, isDesktop } from '@/lib/api';
import type { SessionsResult } from '@/lib/api';

function JsonEditor({ name, title }: { name: string; title: string }) {
  const [text, setText] = useState('');
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.configRead(name).then((res) => {
      setText(res.text);
      setLoaded(true);
      if (res.error) setStatus({ ok: false, msg: res.error });
      else if (!res.exists) setStatus({ ok: false, msg: `${name} not found` });
    });
  }, [name]);

  const validate = (): boolean => {
    try {
      JSON.parse(text);
      setStatus({ ok: true, msg: 'valid JSON' });
      return true;
    } catch (err) {
      setStatus({ ok: false, msg: `invalid JSON: ${(err as Error).message}` });
      return false;
    }
  };

  const save = async () => {
    if (!validate()) return;
    const res = await api.configWrite(name, text);
    setStatus(
      res.ok
        ? { ok: true, msg: `saved (backup written to ${name}.bak)` }
        : { ok: false, msg: res.error ?? 'save failed' },
    );
  };

  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm text-slate-200">{title}</CardTitle>
        <div className="flex items-center gap-2">
          {status && (
            <span className={`text-xs ${status.ok ? 'text-emerald-400' : 'text-rose-400'}`}>
              {status.msg}
            </span>
          )}
          <Button
            size="sm"
            variant="outline"
            className="border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-white"
            onClick={validate}
          >
            Validate
          </Button>
          <Button
            size="sm"
            className="bg-cyan-500 text-slate-950 hover:bg-cyan-400"
            onClick={save}
            disabled={!isDesktop || !loaded}
          >
            <Save className="mr-1 h-4 w-4" />
            Save
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          className="h-72 border-slate-700 bg-slate-950 font-mono text-xs text-slate-200"
          placeholder={isDesktop ? 'loading…' : 'desktop-only: config editing needs Electron'}
        />
      </CardContent>
    </Card>
  );
}

export default function Settings() {
  const [sessions, setSessions] = useState<SessionsResult | null>(null);

  const loadSessions = useCallback(() => {
    api.sessionsRead().then(setSessions);
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const entries = Object.entries(sessions?.data ?? {});

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-100">Settings</h1>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <JsonEditor name="profile.json" title="config/profile.json" />
        <JsonEditor name="searches.json" title="config/searches.json" />
      </div>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-sm text-slate-200">Session sites (data/site_sessions.json)</CardTitle>
        </CardHeader>
        <CardContent>
          {entries.length === 0 ? (
            <p className="text-sm text-slate-500">
              {sessions?.exists ? 'no session entries' : 'file not found — log in via the Browser page first'}
            </p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase text-slate-500">
                  <th className="p-2">Site</th>
                  <th className="p-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([site, value]) => (
                  <tr key={site} className="border-b border-slate-800/50 text-slate-300">
                    <td className="p-2">{site}</td>
                    <td className="p-2">
                      <Badge className="bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/15">
                        saved
                      </Badge>
                      <span className="ml-2 text-xs text-slate-500">
                        {typeof value === 'object' && value !== null
                          ? Object.keys(value as Record<string, unknown>).join(', ')
                          : String(value)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardContent className="pt-6">
          <p className="text-sm text-slate-400">
            The <code className="text-cyan-300">SERPER</code> API key is configured in the pipeline's{' '}
            <code className="text-cyan-300">.env</code> file. For security it is never displayed here.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
