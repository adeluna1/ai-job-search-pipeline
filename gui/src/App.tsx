import { useState } from 'react';
import {
  Bot,
  Briefcase,
  FileSearch,
  Globe,
  LayoutDashboard,
  Search as SearchIcon,
  Settings as SettingsIcon,
  Users,
} from 'lucide-react';
import Dashboard from '@/pages/Dashboard';
import Search from '@/pages/Search';
import Jobs from '@/pages/Jobs';
import Agents from '@/pages/Agents';
import BrowserPage from '@/pages/BrowserPage';
import PaperclipPage from '@/pages/PaperclipPage';
import ResumeMatcherPage from '@/pages/ResumeMatcherPage';
import SettingsPage from '@/pages/SettingsPage';

const NAV = [
  { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { key: 'search', label: 'Search', icon: SearchIcon },
  { key: 'jobs', label: 'Jobs', icon: Briefcase },
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
      <aside className="flex w-56 flex-col border-r border-slate-800 bg-slate-900/40">
        <div className="flex items-center gap-3 border-b border-slate-800 px-5 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/15 font-bold text-cyan-300">
            AI
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-100">AI Job Search</div>
            <div className="text-xs text-slate-500">Pipeline Desktop</div>
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
                className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  active
                    ? 'bg-cyan-500/15 text-cyan-300'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                }`}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="border-t border-slate-800 px-5 py-3 text-[10px] text-slate-600">
          job-hunting pipeline · local-first
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-auto p-6">
        {page === 'dashboard' && <Dashboard />}
        {page === 'search' && <Search />}
        {page === 'jobs' && <Jobs />}
        {page === 'agents' && <Agents />}
        {page === 'browser' && <BrowserPage />}
        {page === 'paperclip' && <PaperclipPage />}
        {page === 'resume-matcher' && <ResumeMatcherPage />}
        {page === 'settings' && <SettingsPage />}
      </main>
    </div>
  );
}
