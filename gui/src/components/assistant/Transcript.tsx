import { Bot, CircleUserRound } from 'lucide-react';
import type { AssistantEvent, AssistantMessage } from '@/lib/api';
import ToolEvent from './ToolEvent';

interface TranscriptProps {
  messages: AssistantMessage[];
  events: AssistantEvent[];
  loading: boolean;
}

export default function Transcript({ messages, events, loading }: TranscriptProps) {
  const visible = messages.filter((item) => item.status !== 'queued' && item.status !== 'cancelled');
  if (!loading && visible.length === 0 && events.length === 0) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center px-8 text-center">
        <Bot className="h-8 w-8 text-cyan-300" aria-hidden="true" />
        <p className="mt-4 text-sm font-medium text-slate-200">Ready for a connection question.</p>
        <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
          Ask the assistant to search, inspect a page with only-cli, process job data, or prepare a local application draft.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-5" aria-live="polite" aria-busy={loading}>
      {visible.map((message) => {
        const ownEvents = events.filter((event) => event.message_id === message.id && [
          'tool_start', 'tool_result', 'approval_required', 'browser_handoff_required', 'message_failed',
        ].includes(event.event_type));
        const user = message.role === 'user';
        return (
          <article key={message.id} className="grid grid-cols-[28px_minmax(0,1fr)] gap-3">
            <div className={`mt-0.5 flex h-7 w-7 items-center justify-center rounded-md ${
              user ? 'bg-slate-800 text-slate-300' : 'bg-cyan-400/10 text-cyan-200'
            }`}>
              {user ? <CircleUserRound className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-500">
                  {user ? 'You' : 'Assistant'}
                </span>
                {message.status !== 'completed' && (
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                    {message.status.replaceAll('_', ' ')}
                  </span>
                )}
              </div>
              <div className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-200">
                {message.content}
              </div>
              {ownEvents.length > 0 && (
                <div className="mt-3 space-y-2">
                  {ownEvents.map((event) => <ToolEvent key={event.id} event={event} />)}
                </div>
              )}
            </div>
          </article>
        );
      })}
      {loading && (
        <div className="flex items-center gap-2 text-xs text-slate-500" role="status">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-300" />
          Assistant is processing the queue.
        </div>
      )}
    </div>
  );
}
