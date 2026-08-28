import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  KeyRound,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import Composer from '@/components/assistant/Composer';
import MessageQueue from '@/components/assistant/MessageQueue';
import Transcript from '@/components/assistant/Transcript';
import { api } from '@/lib/api';
import type {
  AssistantAttachment,
  AssistantEvent,
  AssistantMessage,
  ConversationRecord,
  ProviderCredentialStatus,
  ProviderReadiness,
} from '@/lib/api';

async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',', 2)[1] : value);
    };
    reader.readAsDataURL(file);
  });
}

interface ProviderSnapshot {
  credential: ProviderCredentialStatus;
  providers: ProviderReadiness[];
  provider: string;
  models: string[];
  modelProbeFailed: boolean;
}

function canUseProvider(readiness?: ProviderReadiness): boolean {
  return Boolean(
    readiness?.ready
    && readiness.reachable
    && readiness.authenticated
    && readiness.model_count > 0,
  );
}

function credentialSourceLabel(source?: string): string {
  switch (source) {
    case 'saved':
      return 'Encrypted local storage';
    case 'configured file':
      return 'Configured local file';
    case 'FreeChain file':
      return 'Local FreeChain file';
    case 'environment':
      return 'Process environment';
    case 'unavailable':
    default:
      return 'Unavailable';
  }
}

function safeReadinessDetail(readiness?: ProviderReadiness): string {
  if (!readiness) return 'Provider readiness is unavailable.';
  if (!readiness.credential_configured) return 'Provider key is not configured.';
  if (!readiness.reachable) return 'Provider is unreachable.';
  if (!readiness.authenticated) return 'Provider authorization failed.';
  if (readiness.model_count < 1) return 'Provider returned no usable models.';
  return readiness.ready ? 'Provider and model probe succeeded.' : 'Provider needs attention.';
}

async function providerSnapshot(preferredProvider?: string): Promise<ProviderSnapshot> {
  const [credential, providers] = await Promise.all([
    api.providerCredentialStatus(),
    api.assistantProviders(),
  ]);
  const selected = providers.find((item) => item.name === preferredProvider)
    || providers.find((item) => canUseProvider(item))
    || providers[0];
  const provider = selected?.name || preferredProvider || 'FreeChain';
  let models: string[] = [];
  let modelProbeFailed = false;
  if (canUseProvider(selected)) {
    try {
      const values = await api.assistantModels(provider);
      models = values.filter((item) => typeof item === 'string' && item.trim()).slice(0, 200);
      modelProbeFailed = models.length === 0;
    } catch {
      modelProbeFailed = true;
    }
  }
  return { credential, providers, provider, models, modelProbeFailed };
}

export default function Assistant() {
  const [providers, setProviders] = useState<ProviderReadiness[]>([]);
  const [provider, setProvider] = useState('FreeChain');
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');
  const [modelProbeFailed, setModelProbeFailed] = useState(false);
  const [providerRefreshRequired, setProviderRefreshRequired] = useState(false);
  const [credential, setCredential] = useState<ProviderCredentialStatus | null>(null);
  const [credentialMutation, setCredentialMutation] = useState<'reimport' | 'clear' | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const [conversation, setConversation] = useState<ConversationRecord | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [events, setEvents] = useState<AssistantEvent[]>([]);
  const [attachments, setAttachments] = useState<AssistantAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [shareImages, setShareImages] = useState(false);

  const readiness = useMemo(
    () => providers.find((item) => item.name === provider),
    [provider, providers],
  );
  const providerReady = canUseProvider(readiness)
    && !modelProbeFailed
    && !providerRefreshRequired
    && models.length > 0;
  const conversationId = conversation?.id;

  const refreshTranscript = useCallback(async (id?: string) => {
    const target = id || conversation?.id;
    if (!target) return;
    const [nextMessages, nextEvents] = await Promise.all([
      api.assistantMessages(target),
      api.assistantEvents(target),
    ]);
    setMessages(nextMessages);
    setEvents(nextEvents);
  }, [conversation?.id]);

  const applyProviderSnapshot = (snapshot: ProviderSnapshot, preferredModel?: string) => {
    setCredential(snapshot.credential);
    setProviders(snapshot.providers);
    setProvider(snapshot.provider);
    setModels(snapshot.models);
    setModelProbeFailed(snapshot.modelProbeFailed);
    setProviderRefreshRequired(false);
    setModel(
      preferredModel && snapshot.models.includes(preferredModel)
        ? preferredModel
        : snapshot.models[0] || '',
    );
  };

  const invalidateProviderRuntime = (status?: ProviderCredentialStatus) => {
    if (status) setCredential(status);
    setProviders((current) => current.map((item) => (
      item.name === provider
        ? {
            ...item,
            ready: false,
            reachable: false,
            authenticated: false,
            model_count: 0,
            credential_configured: status?.configured ?? item.credential_configured,
          }
        : item
    )));
    setModels([]);
    setModel('');
    setModelProbeFailed(true);
    setProviderRefreshRequired(true);
  };

  const refreshProvider = async (name?: string, createIfReady = false) => {
    const snapshot = await providerSnapshot(name || provider);
    applyProviderSnapshot(snapshot, model);
    if (snapshot.modelProbeFailed) {
      setError('The provider model probe failed. Restore provider access, then refresh readiness.');
    }
    if (createIfReady && !conversation && snapshot.models.length > 0) {
      const selectedReadiness = snapshot.providers.find((item) => item.name === snapshot.provider);
      if (canUseProvider(selectedReadiness) && !snapshot.modelProbeFailed) {
        const next = await api.assistantCreate({
          provider: snapshot.provider,
          model: snapshot.models[0],
          title: 'Job hunting control',
          allow_image_upload: shareImages,
        });
        setConversation(next);
        setMessages([]);
        setEvents([]);
        setAttachments([]);
      }
    }
    return snapshot;
  };

  const refreshProviderControls = async (name: string) => {
    setBusy(true);
    setError('');
    try {
      await refreshProvider(name, true);
    } catch {
      invalidateProviderRuntime();
      setError('Provider readiness could not be refreshed. Try again after the local provider recovers.');
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const conversations = await api.assistantConversations();
        const current = conversations[0] || null;
        const snapshot = await providerSnapshot(current?.provider);
        if (!active) return;
        applyProviderSnapshot(snapshot, current?.model);
        let activeConversation = current;
        const selectedReadiness = snapshot.providers.find((item) => item.name === snapshot.provider);
        if (!activeConversation && canUseProvider(selectedReadiness) && snapshot.models.length > 0) {
          activeConversation = await api.assistantCreate({
            provider: snapshot.provider,
            model: snapshot.models[0],
            title: 'Job hunting control',
          });
        }
        if (!active || !activeConversation) return;
        setConversation(activeConversation);
        setShareImages(activeConversation.allow_image_upload);
        const [nextMessages, nextEvents] = await Promise.all([
          api.assistantMessages(activeConversation.id),
          api.assistantEvents(activeConversation.id),
        ]);
        if (!active) return;
        setMessages(nextMessages);
        setEvents(nextEvents);
      } catch {
        if (active) {
          setProviders([]);
          setModels([]);
          setModel('');
          setModelProbeFailed(true);
          setProviderRefreshRequired(true);
          setError('The assistant could not connect safely. Refresh provider readiness to try again.');
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  const mutateCredential = async (action: 'reimport' | 'clear') => {
    if (
      action === 'clear'
      && !window.confirm(
        'Clear the encrypted key saved for the current Windows user? The provider will remain unavailable until a key is re-imported.',
      )
    ) return;
    setCredentialMutation(action);
    setAnnouncement('');
    setError('');
    if (action === 'clear') {
      invalidateProviderRuntime();
    }
    try {
      let status: ProviderCredentialStatus;
      try {
        status = action === 'reimport'
          ? await api.providerCredentialReimport()
          : await api.providerCredentialClear();
      } catch {
        setError(
          action === 'reimport'
            ? 'The local key could not be re-imported. Try again or refresh provider readiness.'
            : 'The saved key could not be cleared. Try again before another person uses this account.',
        );
        return;
      }

      const mutationSucceeded = action === 'reimport'
        ? status.configured && status.saved
        : !status.configured && !status.saved;
      if (!mutationSucceeded) {
        invalidateProviderRuntime(status);
        setError(
          action === 'reimport'
            ? 'The local key was found but could not be saved. Check local encryption availability and try again.'
            : 'The saved key could not be cleared. Try again before another person uses this account.',
        );
        return;
      }

      if (action === 'clear') invalidateProviderRuntime(status);
      let snapshot: ProviderSnapshot;
      try {
        snapshot = await refreshProvider(provider, true);
      } catch {
        invalidateProviderRuntime(status);
        setError(
          action === 'reimport'
            ? 'The local key was saved, but provider readiness could not be refreshed. Refresh provider readiness to continue.'
            : 'The saved key was cleared, but provider readiness could not be refreshed. Refresh provider readiness to continue.',
        );
        return;
      }
      const selectedReadiness = snapshot.providers.find((item) => item.name === snapshot.provider);
      const refreshedReady = canUseProvider(selectedReadiness)
        && !snapshot.modelProbeFailed
        && snapshot.models.length > 0;
      setAnnouncement(
        action === 'reimport'
          ? refreshedReady
            ? 'Local key re-imported. Provider is ready.'
            : 'Local key re-imported. Provider still needs attention.'
          : 'Saved key cleared. Provider readiness and models refreshed.',
      );
    } finally {
      setCredentialMutation(null);
    }
  };

  useEffect(() => {
    if (!conversationId) return undefined;
    const interval = window.setInterval(() => {
      void refreshTranscript(conversationId).catch(() => {});
    }, 2000);
    return () => window.clearInterval(interval);
  }, [conversationId, refreshTranscript]);

  const newConversation = async () => {
    if (!providerReady || !model) {
      setError('A ready provider with at least one verified model is required for a new conversation.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const next = await api.assistantCreate({
        provider,
        model,
        title: 'Job hunting control',
        allow_image_upload: shareImages,
      });
      setConversation(next);
      setMessages([]);
      setEvents([]);
      setAttachments([]);
    } catch {
      setError('The conversation could not be created. Refresh provider readiness and try again.');
    } finally {
      setBusy(false);
    }
  };

  const drainQueue = async (conversationId: string) => {
    setBusy(true);
    try {
      for (let count = 0; count < 50; count += 1) {
        const queue = await api.assistantQueue(conversationId);
        if (queue.length === 0) break;
        await api.assistantRun(conversationId);
        await refreshTranscript(conversationId);
      }
    } catch {
      setError('The assistant queue stopped safely. Check provider readiness before retrying.');
    } finally {
      setBusy(false);
      await refreshTranscript(conversationId).catch(() => {});
    }
  };

  const send = async (content: string) => {
    if (!conversation || !providerReady || !model) {
      setError('Restore provider readiness and select a verified model before sending.');
      throw new Error();
    }
    setError('');
    await api.assistantSend(conversation.id, {
      content,
      attachment_ids: attachments.map((item) => item.id),
    });
    setAttachments([]);
    await refreshTranscript(conversation.id);
    void drainQueue(conversation.id);
  };

  const attach = async (files: FileList) => {
    if (!conversation) return;
    setError('');
    try {
      const remaining = Math.max(0, 5 - attachments.length);
      const selected = Array.from(files).slice(0, remaining);
      const uploaded: AssistantAttachment[] = [];
      for (const file of selected) {
        uploaded.push(await api.assistantAttach(conversation.id, {
          filename: file.name,
          mime_type: file.type,
          data_base64: await fileToBase64(file),
        }));
      }
      setAttachments((current) => [...current, ...uploaded]);
    } catch {
      setError('The image could not be attached. Try the file again after checking the local service.');
    }
  };

  const edit = async (message: AssistantMessage) => {
    const content = window.prompt('Edit queued message', message.content);
    if (!content || content.trim() === message.content) return;
    await api.assistantEdit(message.id, content);
    await refreshTranscript(message.conversation_id);
  };

  const cancel = async (message: AssistantMessage) => {
    await api.assistantCancel(message.id);
    await refreshTranscript(message.conversation_id);
  };

  const retry = async (message: AssistantMessage) => {
    const next = await api.assistantRetry(message.id);
    await refreshTranscript(message.conversation_id);
    void drainQueue(next.conversation_id);
  };

  const clear = async () => {
    if (!conversation || !window.confirm('Clear this local transcript and its image attachments?')) return;
    await api.assistantClear(conversation.id);
    setMessages([]);
    setEvents([]);
    setAttachments([]);
  };

  const credentialStatusText = !credential
    ? 'Checking saved key status.'
    : credential.saved
      ? 'Encrypted and saved for the current Windows user.'
      : credential.configured
        ? 'Available for this session, but not saved for the current Windows user.'
        : 'Provider key is not saved for the current Windows user.';
  const recoveryText = providerRefreshRequired
    ? 'Refresh provider readiness to restore model-dependent actions.'
    : !readiness?.credential_configured
    ? 'Re-import a local key, then refresh provider readiness.'
    : !readiness?.reachable
      ? 'Start or reconnect the local provider, then refresh provider readiness.'
      : !readiness?.authenticated
        ? 'Re-import a local key, then refresh provider readiness.'
        : !providerReady
          ? 'No verified models are available. Refresh provider readiness after the provider recovers.'
          : '';

  return (
    <section className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-[1600px] flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-[-0.03em] text-slate-50">Connection assistant</h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Queue requests, add image context, run only-cli and pipeline tools, and keep external actions behind exact approval.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy || !conversation}
            onClick={() => void clear()}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 px-3 text-xs text-slate-400 hover:bg-slate-900 hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-400 disabled:opacity-40"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear transcript
          </button>
          <button
            type="button"
            disabled={busy || loading || Boolean(credentialMutation) || !providerReady || !model}
            onClick={() => void newConversation()}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-cyan-300 px-3 text-xs font-semibold text-cyan-950 hover:bg-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-100 disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
            New conversation
          </button>
        </div>
      </header>

      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40 shadow-[0_18px_55px_rgba(0,0,0,0.28)]">
        <div className="grid gap-3 border-b border-slate-800 p-4 md:grid-cols-[minmax(180px,1fr)_minmax(180px,1fr)_auto]">
          <label className="text-[11px] font-semibold text-slate-500">
            Provider
            <select
              value={provider}
              disabled={loading || busy || Boolean(credentialMutation)}
              onChange={(event) => {
                setProvider(event.target.value);
                setModels([]);
                setModel('');
                void refreshProviderControls(event.target.value);
              }}
              className="mt-2 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {providers.map((item) => <option key={item.name}>{item.name}</option>)}
            </select>
          </label>
          <label className="text-[11px] font-semibold text-slate-500">
            Model
            <select
              value={model}
              disabled={models.length === 0 || busy || Boolean(credentialMutation)}
              onChange={(event) => setModel(event.target.value)}
              className="mt-2 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {models.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <button
            type="button"
            disabled={loading || busy || Boolean(credentialMutation)}
            onClick={() => void refreshProviderControls(provider)}
            aria-label="Refresh provider readiness and models"
            className="mt-5 inline-flex h-10 w-10 items-center justify-center rounded-md border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>

        <div className="border-b border-slate-800 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2 py-1 text-[10px] font-medium ${
              providerReady
                ? 'border-emerald-800 bg-emerald-950/40 text-emerald-300'
                : 'border-amber-800 bg-amber-950/35 text-amber-300'
            }`}>
              {providerReady ? 'Provider ready' : 'Provider needs attention'}
            </span>
            {providerReady ? (
              <span className="rounded-full border border-slate-700 px-2 py-1 text-[10px] text-slate-400">
                {models.length} model{models.length === 1 ? '' : 's'}
              </span>
            ) : (
              <span className="rounded-full border border-slate-700 px-2 py-1 text-[10px] text-slate-400">
                No verified models
              </span>
            )}
            <label className="ml-auto flex cursor-pointer items-center gap-2 text-[10px] text-slate-500">
              <input
                type="checkbox"
                checked={shareImages}
                onChange={(event) => setShareImages(event.target.checked)}
                className="h-3.5 w-3.5 accent-cyan-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              />
              Share images with provider on new conversations
            </label>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
            <div className="min-w-0 text-xs leading-5 text-slate-400">
              <p className="break-words text-slate-300">
                {providerRefreshRequired
                  ? 'Provider readiness must be refreshed.'
                  : safeReadinessDetail(readiness)}
              </p>
              {recoveryText && <p className="mt-1 break-words text-amber-300">{recoveryText}</p>}
              <p className="mt-2 inline-flex max-w-full items-start gap-1.5 break-words text-slate-500">
                <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 break-words">
                  {credentialStatusText} Source: {credentialSourceLabel(credential?.source)}.
                </span>
              </p>
              <p className="mt-1 break-words text-slate-500">
                The encrypted key is tied to the current Windows user and should be cleared before another person uses the same account.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 lg:justify-end">
              <button
                type="button"
                disabled={Boolean(credentialMutation) || loading}
                onClick={() => void mutateCredential('reimport')}
                className="inline-flex h-9 items-center rounded-md border border-slate-700 px-3 text-xs font-medium text-slate-300 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {credentialMutation === 'reimport' ? 'Re-importing local key' : 'Re-import local key'}
              </button>
              <button
                type="button"
                disabled={Boolean(credentialMutation) || loading || !credential?.saved}
                onClick={() => void mutateCredential('clear')}
                className="inline-flex h-9 items-center rounded-md border border-slate-700 px-3 text-xs font-medium text-slate-300 hover:border-rose-800 hover:text-rose-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {credentialMutation === 'clear' ? 'Clearing saved key' : 'Clear saved key'}
              </button>
            </div>
          </div>
          <div role="status" aria-live="polite" aria-atomic="true" className="min-h-5 pt-2 text-xs text-cyan-200">
            {announcement}
          </div>
        </div>

        <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3 text-xs text-slate-500">
          <ShieldCheck className="h-3.5 w-3.5 text-cyan-300" />
          {conversation && providerReady
            ? `Ready in ${conversation.title}`
            : conversation
              ? 'Existing conversation preserved. Restore provider access to continue.'
              : providerReady
                ? 'Ready to create a conversation'
                : 'Connecting to the local control service'}
        </div>

        {error && (
          <div role="alert" className="border-b border-rose-900 bg-rose-950/35 px-4 py-3 text-sm text-rose-200">
            {error}
          </div>
        )}

        <div className="grid min-h-[460px] lg:grid-cols-[minmax(0,1fr)_288px]">
          <div className="flex min-w-0 flex-col">
            <div className="min-h-0 flex-1 overflow-auto">
              <Transcript messages={messages} events={events} loading={loading || busy} />
            </div>
            <Composer
              attachments={attachments}
              disabled={!conversation || loading || !providerReady || !model}
              onAttach={(files) => void attach(files)}
              onRemoveAttachment={(id) => setAttachments((items) => items.filter((item) => item.id !== id))}
              onSend={send}
            />
          </div>
          <MessageQueue messages={messages} onEdit={edit} onCancel={cancel} onRetry={retry} />
        </div>
      </div>
    </section>
  );
}
