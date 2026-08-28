import { AlertTriangle, CheckCircle2, KeyRound, LoaderCircle, MonitorUp, Wrench } from 'lucide-react';
import type { AssistantEvent } from '@/lib/api';

const ICONS = {
  tool_start: LoaderCircle,
  tool_result: CheckCircle2,
  approval_required: KeyRound,
  browser_handoff_required: MonitorUp,
  message_failed: AlertTriangle,
} as const;

export default function ToolEvent({ event }: { event: AssistantEvent }) {
  const Icon = ICONS[event.event_type as keyof typeof ICONS] || Wrench;
  const toolName = typeof event.payload.tool_name === 'string'
    ? event.payload.tool_name
    : event.event_type.replaceAll('_', ' ');
  const summary = typeof event.payload.summary === 'string' ? event.payload.summary : '';
  const warning = event.event_type === 'approval_required'
    || event.event_type === 'browser_handoff_required'
    || event.event_type === 'message_failed';

  return (
    <details className={`group rounded-md border px-3 py-2 text-xs ${
      warning
        ? 'border-amber-800/80 bg-amber-950/25 text-amber-100'
        : 'border-slate-800 bg-slate-950/70 text-slate-400'
    }`}>
      <summary className="flex cursor-pointer list-none items-center gap-2 font-medium outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
        <Icon className={`h-3.5 w-3.5 ${event.event_type === 'tool_start' ? 'animate-spin' : ''}`} />
        <span className="truncate">{toolName}</span>
        <span className="ml-auto text-[10px] uppercase tracking-[0.1em] opacity-70">
          {event.event_type.replaceAll('_', ' ')}
        </span>
      </summary>
      <div className="mt-2 border-t border-current/15 pt-2 leading-5 opacity-80">
        {summary || 'No content was stored in the tool audit event.'}
      </div>
    </details>
  );
}
