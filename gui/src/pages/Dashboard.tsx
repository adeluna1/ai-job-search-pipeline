import { useCallback, useEffect, useState } from 'react';
import { Power, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { api, isDesktop } from '@/lib/api';
import type { DoctorResult, ServicesMap, SessionsResult, StartableService } from '@/lib/api';

function StatusDot({ up }: { up: boolean }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${up ? 'bg-emerald-400' : 'bg-rose-500'}`}
    />
  );
}

function serviceFromDoctor(doctorText: string, key: string): { found: boolean; ok: boolean } {
  const line = doctorText
    .split('\n')
    .find((l) => l.toLowerCase().includes(key.toLowerCase()));
  if (!line) return { found: false, ok: false };
  return { found: true, ok: !/fail|missing|error|not found/i.test(line) };
}

export default function Dashboard() {
  const [doctor, setDoctor] = useState<DoctorResult | null>(null);
  const [doctorBusy, setDoctorBusy] = useState(false);
  const [services, setServices] = useState<ServicesMap | null>(null);
  const [sessions, setSessions] = useState<SessionsResult | null>(null);
  const [engineBusy, setEngineBusy] = useState<string | null>(null);

  const runDoctor = useCallback(async () => {
    setDoctorBusy(true);
    try {
      setDoctor(await api.doctor());
    } finally {
      setDoctorBusy(false);
    }
  }, []);

  const refreshServices = useCallback(async () => {
    setServices(await api.services());
  }, []);

  const startService = useCallback(
    async (service: Exclude<StartableService, 'all'>) => {
      setEngineBusy(service);
      try {
        await api.servicesStart(service);
        await refreshServices();
      } finally {
        setEngineBusy(null);
      }
    },
    [refreshServices],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void runDoctor();
      void refreshServices();
      void api.sessionsRead().then(setSessions);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [runDoctor, refreshServices]);

  const webclaw = doctor ? serviceFromDoctor(doctor.output, 'webclaw') : null;
  const serper = doctor ? serviceFromDoctor(doctor.output, 'serper') : null;
  const sessionSites = sessions?.data ? Object.keys(sessions.data) : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Expedient Employment</h1>
          <p className="text-sm text-slate-400">
            Job-hunting pipeline control center
            {!isDesktop && ' · browser preview (demo data)'}
          </p>
        </div>
        <Button
          variant="outline"
          className="border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-white"
          onClick={runDoctor}
          disabled={doctorBusy}
        >
          <RefreshCw className={`mr-2 h-4 w-4 ${doctorBusy ? 'animate-spin' : ''}`} />
          Re-run doctor
        </Button>
      </div>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-slate-200">Pipeline doctor</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-4 text-xs text-slate-300">
            {doctor ? doctor.output || '(no output)' : 'Running doctor…'}
          </pre>
          {doctor && (
            <p className="mt-2 text-xs text-slate-500">exit code: {doctor.code ?? 'n/a'}</p>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <ServiceTile
          title="WebClaw"
          subtitle="scraping service (via doctor)"
          up={webclaw ? (webclaw.found && webclaw.ok) : null}
        />
        <ServiceTile
          title="Serper"
          subtitle="search API key (via doctor)"
          up={serper ? (serper.found && serper.ok) : null}
        />
        <ServiceTile
          title="AWB bridge"
          subtitle={
            services?.awb.up
              ? services.awb.isBridge
                ? 'Agent Web Browser on :7896'
                : `port 7896 serves "${services.awb.app ?? 'unknown'}"`
              : 'down (:7896)'
          }
          up={services ? services.awb.up && !!services.awb.isBridge : null}
          warn={services?.awb.up && !services.awb.isBridge}
        />
        <ServiceTile
          title="Paperclip"
          subtitle={services?.paperclip.up ? 'online (:3100)' : 'offline (:3100)'}
          up={services ? services.paperclip.up : null}
          action={
            services && !services.paperclip.up
              ? {
                  label: engineBusy === 'paperclip' ? 'Starting…' : 'Engine Start',
                  busy: engineBusy === 'paperclip',
                  onClick: () => startService('paperclip'),
                }
              : undefined
          }
        />
        <ServiceTile
          title="Resume-Matcher"
          subtitle={services?.resumeMatcher.up ? 'online (:3000)' : 'offline (:3000)'}
          up={services ? services.resumeMatcher.up : null}
          action={
            services && !services.resumeMatcher.up
              ? {
                  label: engineBusy === 'resume-matcher' ? 'Starting…' : 'Engine Start',
                  busy: engineBusy === 'resume-matcher',
                  onClick: () => startService('resume-matcher'),
                }
              : undefined
          }
        />
        <Card className="border-slate-800 bg-slate-900/60">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-slate-200">Session sites</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {sessionSites.length > 0 ? (
              sessionSites.map((s) => (
                <Badge key={s} className="bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/15">
                  {s}
                </Badge>
              ))
            ) : (
              <span className="text-xs text-slate-500">
                {sessions?.exists === false ? 'no saved sessions yet' : 'none recorded'}
              </span>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ServiceTile({
  title,
  subtitle,
  up,
  warn,
  action,
}: {
  title: string;
  subtitle: string;
  up: boolean | null;
  warn?: boolean;
  action?: { label: string; busy: boolean; onClick: () => void };
}) {
  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-slate-200">{title}</CardTitle>
          {up === null ? (
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-slate-600" />
          ) : warn ? (
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-amber-400" />
          ) : (
            <StatusDot up={up} />
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-slate-400">{subtitle}</p>
        {action && (
          <Button
            size="sm"
            variant="outline"
            className="border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-white"
            onClick={action.onClick}
            disabled={action.busy || !isDesktop}
          >
            <Power className="mr-1 h-3 w-3" />
            {action.label}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
