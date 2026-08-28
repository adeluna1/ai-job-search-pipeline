import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, ExternalLink, MonitorUp, RotateCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { api, isDesktop } from '@/lib/api';
import type { WebviewElement } from '@/types/webview.d';

interface SiteTab {
  key: string;
  label: string;
  fallbackUrl: string;
}

const TABS: SiteTab[] = [
  { key: 'linkedin', label: 'LinkedIn', fallbackUrl: 'https://www.linkedin.com/login' },
  { key: 'glassdoor', label: 'Glassdoor', fallbackUrl: 'https://www.glassdoor.com/profile/login_input.htm' },
  { key: 'zip_recruiter', label: 'ZipRecruiter', fallbackUrl: 'https://www.ziprecruiter.com/login' },
  { key: 'indeed', label: 'Indeed', fallbackUrl: 'https://secure.indeed.com/auth' },
];

export default function BrowserPage() {
  const [active, setActive] = useState(TABS[0].key);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [awbBusy, setAwbBusy] = useState(false);
  const [awbStatus, setAwbStatus] = useState<string | null>(null);
  const webviewRefs = useRef<Record<string, WebviewElement | null>>({});

  // login:open support — resolve each site's login_url from access_policy.json
  useEffect(() => {
    (async () => {
      const resolved: Record<string, string> = {};
      for (const t of TABS) {
        const res = await api.loginUrl(t.key);
        resolved[t.key] = res.ok && res.url ? res.url : t.fallbackUrl;
      }
      setUrls(resolved);
    })();
  }, []);

  const openLoginTab = useCallback(async (siteKey: string) => {
    const res = await api.loginUrl(siteKey);
    if (res.ok && res.url) {
      setUrls((prev) => ({ ...prev, [siteKey]: res.url as string }));
    }
    setActive(siteKey);
  }, []);

  const launchAwb = async () => {
    setAwbBusy(true);
    setAwbStatus(null);
    try {
      const res = await api.awbLaunch();
      if (res.error) setAwbStatus(`error: ${res.error}`);
      else setAwbStatus(res.bridgeUp ? 'bridge online: Agent Web Browser (:7896)' : 'launched, bridge not detected yet');
    } finally {
      setAwbBusy(false);
    }
  };

  const wv = webviewRefs.current[active];

  return (
    <div className="flex h-full flex-col space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-100">Browser</h1>
        <div className="flex items-center gap-3">
          {awbStatus && <span className="text-xs text-slate-400">{awbStatus}</span>}
          <Button
            variant="outline"
            className="border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-white"
            onClick={launchAwb}
            disabled={awbBusy || !isDesktop}
          >
            <MonitorUp className="mr-2 h-4 w-4" />
            {awbBusy ? 'Launching…' : 'Open standalone AWB'}
          </Button>
        </div>
      </div>

      <div className="rounded-md border border-cyan-900/50 bg-cyan-950/20 px-4 py-2 text-xs text-cyan-300">
        Log in once — sessions persist locally (partition <code>persist:ee-browser</code>).
      </div>

      <div className="flex items-center gap-2">
        {TABS.map((t) => (
          <Button
            key={t.key}
            size="sm"
            variant={active === t.key ? 'default' : 'outline'}
            className={
              active === t.key
                ? 'bg-cyan-500 text-slate-950 hover:bg-cyan-400'
                : 'border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-white'
            }
            onClick={() => openLoginTab(t.key)}
          >
            {t.label}
          </Button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            className="text-slate-300 hover:bg-slate-800"
            onClick={() => wv?.goBack()}
            disabled={!isDesktop}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="text-slate-300 hover:bg-slate-800"
            onClick={() => wv?.goForward()}
            disabled={!isDesktop}
          >
            <ArrowRight className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="text-slate-300 hover:bg-slate-800"
            onClick={() => wv?.reload()}
            disabled={!isDesktop}
          >
            <RotateCw className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="text-slate-300 hover:bg-slate-800"
            onClick={() => {
              const url = wv?.getURL?.() ?? urls[active];
              if (url) window.open(url, '_blank');
            }}
          >
            <ExternalLink className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <Card className="min-h-0 flex-1 border-slate-800 bg-slate-900/60">
        <CardContent className="h-full p-0">
          {isDesktop ? (
            <div className="relative h-full">
              {TABS.map((t) => (
                <webview
                  key={t.key}
                  ref={(el) => {
                    webviewRefs.current[t.key] = el as WebviewElement | null;
                  }}
                  src={urls[t.key] ?? t.fallbackUrl}
                  partition="persist:ee-browser"
                  className="absolute inset-0 h-full w-full"
                  style={{ display: active === t.key ? 'flex' : 'none' }}
                />
              ))}
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
              <Badge className="bg-slate-800 text-slate-300 hover:bg-slate-800">
                desktop-only
              </Badge>
              <p className="max-w-md text-sm text-slate-400">
                Embedded job-board tabs render as Electron <code>&lt;webview&gt;</code> panels.
                Run the desktop app to log in to LinkedIn, Glassdoor, ZipRecruiter, and Indeed.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
