import { useState } from 'react';
import {
  Bot,
  Briefcase,
  CalendarClock,
  ClipboardCheck,
  FileSearch,
  Globe,
  LayoutDashboard,
  MessageSquareText,
  Search as SearchIcon,
  Settings as SettingsIcon,
  Wrench,
  Users,
} from 'lucide-react';
import Dashboard from '@/pages/Dashboard';
import Search from '@/pages/Search';
import Jobs from '@/pages/Jobs';
import Applications from '@/pages/Applications';
import Agents from '@/pages/Agents';
import BrowserPage from '@/pages/BrowserPage';
import PaperclipPage from '@/pages/PaperclipPage';
import ResumeMatcherPage from '@/pages/ResumeMatcherPage';
import SettingsPage from '@/pages/SettingsPage';
import Assistant from '@/pages/Assistant';
import Automations from '@/pages/Automations';
import WebWorkbench from '@/pages/WebWorkbench';

const NAV = [
  { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { key: 'assistant', label: 'Assistant', icon: MessageSquareText },
  { key: 'automations', label: 'Automations', icon: CalendarClock },
  { key: 'workbench', label: 'Web workbench', icon: Wrench },
  { key: 'search', label: 'Search', icon: SearchIcon },
  { key: 'jobs', label: 'Jobs', icon: Briefcase },
  { key: 'applications', label: 'Applications', icon: ClipboardCheck },
  { key: 'agents', label: 'Agents', icon: Users },
  { key: 'browser', label: 'Browser', icon: Globe },
  { key: 'paperclip', label: 'Paperclip', icon: Bot },
  { key: 'resume-matcher', label: 'Resume-Matcher', icon: FileSearch },
  { key: 'settings', label: 'Settings', icon: SettingsIcon },
] as const;

type PageKey = (typeof NAV)[number]['key'];

export default function App() {
  const [page, setPage] = useState<PageKey>('dashboard');

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <aside className="flex w-[76px] shrink-0 flex-col border-r border-slate-800 bg-slate-900/55 lg:w-56">
        <div className="flex items-center gap-3 border-b border-slate-800 px-4 py-5 lg:px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/15 font-bold text-cyan-300">
            EE
          </div>
          <div className="hidden lg:block">
            <div className="text-sm font-semibold text-slate-100">Expedient</div>
            <div className="text-xs text-slate-500">Employment</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = page === item.key;
            return (
              <button
                key={item.key}
                onClick={() => setPage(item.key)}
                title={item.label}
                className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  active
                    ? 'bg-cyan-500/15 text-cyan-300'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                }`}
              >
                <Icon className="h-4 w-4" />
                <span className="hidden lg:inline">{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="hidden border-t border-slate-800 px-5 py-3 text-[10px] text-slate-600 lg:block">
          job-hunting pipeline · local-first
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-auto p-4 md:p-6">
        {page === 'dashboard' && <Dashboard />}
        {page === 'assistant' && <Assistant />}
        {page === 'automations' && <Automations />}
        {page === 'workbench' && <WebWorkbench />}
        {page === 'search' && <Search />}
        {page === 'jobs' && <Jobs />}
        {page === 'applications' && <Applications />}
        {page === 'agents' && <Agents />}
        {page === 'browser' && <BrowserPage />}
        {page === 'paperclip' && <PaperclipPage />}
        {page === 'resume-matcher' && <ResumeMatcherPage />}
        {page === 'settings' && <SettingsPage />}
      </main>
    </div>
  );
}
