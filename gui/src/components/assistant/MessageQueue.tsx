import { Pencil, RotateCcw, X } from 'lucide-react';
import type { AssistantMessage } from '@/lib/api';

interface MessageQueueProps {
  messages: AssistantMessage[];
  onEdit: (message: AssistantMessage) => void;
  onCancel: (message: AssistantMessage) => void;
  onRetry: (message: AssistantMessage) => void;
}

export default function MessageQueue({ messages, onEdit, onCancel, onRetry }: MessageQueueProps) {
  const queued = messages.filter((item) => item.role === 'user' && item.status === 'queued');
  const stopped = messages.filter((item) => item.role === 'user' && [
    'failed', 'cancelled', 'awaiting_approval', 'needs_handoff',
  ].includes(item.status)).slice(-4);
  return (
    <aside className="border-l border-slate-800 bg-slate-950/50 lg:w-72" aria-label="Message queue">
      <div className="border-b border-slate-800 px-4 py-3">
        <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Message queue</div>
        <div className="mt-1 text-xs text-slate-600">{queued.length} waiting</div>
      </div>
      <div className="max-h-64 space-y-2 overflow-auto p-3 lg:max-h-none">
        {queued.map((message, index) => (
          <div key={message.id} className="rounded-md border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.1em] text-cyan-300">
              <span>Queue {index + 1}</span>
              <span className="ml-auto text-slate-600">waiting</span>
            </div>
            <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-300">{message.content}</p>
            <div className="mt-3 flex gap-1">
              <button
                type="button"
                onClick={() => onEdit(message)}
                className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-400"
                aria-label="Edit queued message"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => onCancel(message)}
                className="rounded p-1.5 text-rose-400 hover:bg-rose-950 hover:text-rose-200 focus:outline-none focus:ring-2 focus:ring-cyan-400"
                aria-label="Cancel queued message"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ))}
        {queued.length === 0 && (
          <p className="px-1 py-5 text-xs leading-5 text-slate-600">New messages wait here while the assistant is busy.</p>
        )}
        {stopped.map((message) => (
          <button
            key={message.id}
            type="button"
            onClick={() => onRetry(message)}
            className="flex w-full items-center gap-2 rounded-md border border-slate-800 px-3 py-2 text-left text-xs text-slate-400 hover:border-slate-700 hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-400"
          >
            <RotateCcw className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">Retry {message.status.replaceAll('_', ' ')}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
