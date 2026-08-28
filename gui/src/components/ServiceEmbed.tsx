import { useCallback, useEffect, useState } from 'react';
import { Power, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { api, isDesktop } from '@/lib/api';
import type { ServicesMap, StartableService } from '@/lib/api';

const OUTLINE_BTN =
  'border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-white';

interface ServiceEmbedProps {
  title: string;
  subtitle: string;
  service: Exclude<StartableService, 'all'>;
  serviceKey: keyof Pick<ServicesMap, 'paperclip' | 'resumeMatcher'>;
  url: string;
  partition: string;
}

export default function ServiceEmbed({
  title,
  subtitle,
  service,
  serviceKey,
  url,
  partition,
}: ServiceEmbedProps) {
  const [up, setUp] = useState<boolean | null>(null); // null = checking
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [dockerMissing, setDockerMissing] = useState(false);

  const check = useCallback(async () => {
    const services = await api.services();
    setUp(services[serviceKey].up);
    return services[serviceKey].up;
  }, [serviceKey]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void check(); }, 0);
    return () => window.clearTimeout(timer);
  }, [check]);

  const start = async () => {
    setBusy(true);
    setMessage('launching…');
    setDockerMissing(false);
    try {
      const res = await api.servicesStart(service);
      const r = serviceKey === 'paperclip' ? res.paperclip : res.resumeMatcher;
      const nowUp = await check();
      if (nowUp) {
        setMessage(null);
      } else {
        if (r?.dockerMissing) setDockerMissing(true);
        setMessage(r?.error ? `failed: ${r.error}` : 'failed to start — see logs');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{title}</h1>
          <p className="text-sm text-slate-400">{subtitle}</p>
        </div>
        <Button
          variant="outline"
          className={OUTLINE_BTN}
          onClick={() => check()}
          disabled={busy}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Re-check
        </Button>
      </div>

      {up ? (
        isDesktop ? (
          <Card className="min-h-0 flex-1 border-slate-800 bg-slate-900/60">
            <CardContent className="h-full p-0">
              <webview src={url} partition={partition} className="h-full w-full" />
            </CardContent>
          </Card>
        ) : (
          <p className="text-sm text-slate-500">
            embedded view is desktop-only — open {url} in your browser.
          </p>
        )
      ) : (
        <Card className="flex flex-1 items-center justify-center border-slate-800 bg-slate-900/60">
          <CardContent className="flex flex-col items-center gap-4 p-8 text-center">
            <p className="text-sm text-slate-400">
              {up === null ? `Checking ${title} status…` : `${title} is offline.`}
            </p>
            {up === false && (
              <Button
                onClick={start}
                disabled={busy || !isDesktop}
                className="bg-cyan-500 text-slate-950 hover:bg-cyan-400"
              >
                <Power className="mr-2 h-4 w-4" />
                {busy ? 'Starting…' : 'Engine Start'}
              </Button>
            )}
            {dockerMissing && (
              <p className="max-w-md text-xs text-amber-300">
                Docker was not found on PATH — Docker Desktop is required to run Resume-Matcher.
              </p>
            )}
            {message && (
              <p className={`max-w-md text-xs ${message.startsWith('failed') ? 'text-rose-400' : 'text-slate-400'}`}>
                {message}
              </p>
            )}
            {!isDesktop && (
              <p className="text-xs text-slate-500">desktop-only: launch via Electron to start services</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
