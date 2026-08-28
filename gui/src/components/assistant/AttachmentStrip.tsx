import { Image, X } from 'lucide-react';
import type { AssistantAttachment } from '@/lib/api';

interface AttachmentStripProps {
  attachments: AssistantAttachment[];
  onRemove: (id: string) => void;
}

export default function AttachmentStrip({ attachments, onRemove }: AttachmentStripProps) {
  if (attachments.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2" aria-label="Images attached to the queued message">
      {attachments.map((item) => (
        <div
          key={item.id}
          className="flex max-w-56 items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-2.5 py-2 text-xs text-slate-300"
        >
          <Image className="h-3.5 w-3.5 shrink-0 text-cyan-300" aria-hidden="true" />
          <span className="truncate">{item.filename}</span>
          <button
            type="button"
            onClick={() => onRemove(item.id)}
            aria-label={`Remove ${item.filename}`}
            className="ml-auto rounded p-0.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-400"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
