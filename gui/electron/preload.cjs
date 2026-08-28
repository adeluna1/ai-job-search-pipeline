// Expedient Employment — preload bridge
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  doctor: () => ipcRenderer.invoke('doctor'),
  services: () => ipcRenderer.invoke('services'),
  servicesStart: (service) => ipcRenderer.invoke('services:start', { service }),
  searchSpawn: (args) => ipcRenderer.invoke('search:spawn', args),
  onSearchLog: (cb) => {
    const listener = (_e, payload) => cb(payload);
    ipcRenderer.on('search:log', listener);
    return () => ipcRenderer.removeListener('search:log', listener);
  },
  jobsRead: () => ipcRenderer.invoke('jobs:read'),
  reportOpen: () => ipcRenderer.invoke('report:open'),
  applicationsRead: () => ipcRenderer.invoke('applications:read'),
  applicationsRefresh: () => ipcRenderer.invoke('applications:refresh'),
  applicationsFlag: (identityKey, flag) => (
    ipcRenderer.invoke('applications:flag', { identityKey, flag })
  ),
  applicationsUndo: (identityKey) => (
    ipcRenderer.invoke('applications:undo', { identityKey })
  ),
  applicationsReportOpen: () => ipcRenderer.invoke('applications:report-open'),
  agentsList: () => ipcRenderer.invoke('agents:list'),
  configRead: (name) => ipcRenderer.invoke('config:read', name),
  configWrite: (name, text) => ipcRenderer.invoke('config:write', name, text),
  sessionsRead: () => ipcRenderer.invoke('sessions:read'),
  awbLaunch: () => ipcRenderer.invoke('awb:launch'),
  loginUrl: (siteKey) => ipcRenderer.invoke('login:url', siteKey),
  controlStatus: () => ipcRenderer.invoke('control:status'),
  providerCredentialStatus: () => ipcRenderer.invoke('provider-credential:status'),
  providerCredentialReimport: () => ipcRenderer.invoke('provider-credential:reimport'),
  providerCredentialClear: () => ipcRenderer.invoke('provider-credential:clear'),
  assistantProviders: () => ipcRenderer.invoke('assistant:providers'),
  assistantModels: (provider) => ipcRenderer.invoke('assistant:models', provider),
  assistantConversations: () => ipcRenderer.invoke('assistant:conversations'),
  assistantCreate: (input) => ipcRenderer.invoke('assistant:create', input),
  assistantMessages: (conversationId) => ipcRenderer.invoke('assistant:messages', conversationId),
  assistantQueue: (conversationId) => ipcRenderer.invoke('assistant:queue', conversationId),
  assistantEvents: (conversationId) => ipcRenderer.invoke('assistant:events', conversationId),
  assistantAttach: (conversationId, input) => (
    ipcRenderer.invoke('assistant:attach', conversationId, input)
  ),
  assistantSend: (conversationId, input) => (
    ipcRenderer.invoke('assistant:send', conversationId, input)
  ),
  assistantRun: (conversationId) => ipcRenderer.invoke('assistant:run', conversationId),
  assistantEdit: (messageId, content) => ipcRenderer.invoke('assistant:edit', messageId, content),
  assistantCancel: (messageId) => ipcRenderer.invoke('assistant:cancel', messageId),
  assistantRetry: (messageId) => ipcRenderer.invoke('assistant:retry', messageId),
  assistantClear: (conversationId) => ipcRenderer.invoke('assistant:clear', conversationId),
  toolsList: () => ipcRenderer.invoke('tools:list'),
  workflowsDryRun: (input) => ipcRenderer.invoke('workflows:dry-run', input),
  workflowsRun: (input) => ipcRenderer.invoke('workflows:run', input),
  schedulesList: () => ipcRenderer.invoke('schedules:list'),
  schedulesCreate: (input) => ipcRenderer.invoke('schedules:create', input),
  schedulesToggle: (scheduleId, enabled) => (
    ipcRenderer.invoke('schedules:toggle', scheduleId, enabled)
  ),
  schedulesRunDue: () => ipcRenderer.invoke('schedules:run-due'),
  schedulesHistory: (scheduleId) => ipcRenderer.invoke('schedules:history', scheduleId),
  schedulesInstallWake: () => ipcRenderer.invoke('schedules:install-wake'),
});
