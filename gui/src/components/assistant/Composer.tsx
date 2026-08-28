import { useRef, useState } from 'react';
import { ImagePlus, Send } from 'lucide-react';
import type { AssistantAttachment } from '@/lib/api';
import AttachmentStrip from './AttachmentStrip';

interface ComposerProps {
  attachments: AssistantAttachment[];
  disabled?: boolean;
  onAttach: (files: FileList) => void;
  onRemoveAttachment: (id: string) => void;
  onSend: (content: string) => Promise<void>;
}

export default function Composer({
  attachments,
  disabled,
  onAttach,
  onRemoveAttachment,
  onSend,
}: ComposerProps) {
  const [content, setContent] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async () => {
    const value = content.trim();
    if (!value || disabled) return;
    setContent('');
    try {
      await onSend(value);
    } catch {
      setContent(value);
    }
  };

  return (
    <div className="space-y-3 border-t border-slate-800 bg-slate-900/65 p-4">
      <AttachmentStrip attachments={attachments} onRemove={onRemoveAttachment} />
      <label className="block text-[11px] font-semibold text-slate-500" htmlFor="assistant-message">
        Message
      </label>
      <textarea
        id="assistant-message"
        value={content}
        disabled={disabled}
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            void submit();
          }
        }}
        placeholder="Describe what you want to search, process, draft, or troubleshoot"
        className="min-h-24 w-full resize-y rounded-md border border-slate-700 bg-slate-950 px-3 py-3 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/25 disabled:opacity-50"
      />
      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          multiple
          className="hidden"
          onChange={(event) => {
            if (event.target.files) onAttach(event.target.files);
            event.target.value = '';
          }}
        />
        <button
          type="button"
          disabled={disabled || attachments.length >= 5}
          onClick={() => inputRef.current?.click()}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-3 text-xs font-medium text-slate-300 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:opacity-40"
        >
          <ImagePlus className="h-4 w-4" />
          Attach images
        </button>
        <span className="text-[10px] text-slate-600">Enter to add, Shift+Enter for newline</span>
        <button
          type="button"
          disabled={disabled || !content.trim()}
          onClick={() => void submit()}
          className="ml-auto inline-flex h-9 items-center gap-2 rounded-md bg-cyan-300 px-4 text-xs font-semibold text-cyan-950 hover:bg-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Send className="h-3.5 w-3.5" />
          Add to queue
        </button>
      </div>
    </div>
  );
}
