// AI Job Search Pipeline — Electron main process
const { app, BrowserWindow, dialog, ipcMain, session, shell } = require('electron');
const path = require('path');
const os = require('os');
const fs = require('fs');
const http = require('http');
const { spawn } = require('child_process');
const {
  DEFAULT_LOCATIONS,
  DEFAULT_QUERY,
  buildPipelineSearchArgs,
  isAllowedSessionUrl,
} = require('./safety.cjs');

const DEVELOPMENT_PIPELINE_ROOT = path.resolve(__dirname, '..', '..');
let PIPELINE_ROOT = DEVELOPMENT_PIPELINE_ROOT;
const GUI_ROOT = path.resolve(__dirname, '..');

let mainWindow = null;
// child processes spawned by this app instance (killed on quit)
const spawnedChildren = new Set();

// ── single instance: everything in one window ──────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

function isPipelineRoot(candidate) {
  if (!candidate) return false;
  const resolved = path.resolve(candidate);
  return (
    fs.existsSync(path.join(resolved, 'run.ps1'))
    && fs.existsSync(path.join(resolved, 'job_pipeline'))
    && fs.existsSync(path.join(resolved, 'config', 'profile.json'))
  );
}

function findWorkspacePipelineRoot() {
  const candidates = [
    process.env.AI_JOB_PIPELINE_ROOT,
    path.resolve(path.dirname(process.execPath), '..', '..', '..'),
  ].filter(Boolean);
  return candidates.find((candidate) => (
    isPipelineRoot(candidate)
    && fs.existsSync(path.join(path.resolve(candidate), 'data', 'applied_jobs.json'))
  )) || '';
}

function preparePipelineRoot() {
  if (!app.isPackaged) return DEVELOPMENT_PIPELINE_ROOT;
  const workspace = findWorkspacePipelineRoot();
  if (workspace) return path.resolve(workspace);
  const bundled = path.join(process.resourcesPath, 'pipeline');
  const runtime = path.join(app.getPath('userData'), 'pipeline');
  fs.mkdirSync(runtime, { recursive: true });

  for (const directory of ['job_pipeline', 'scripts', 'docs']) {
    const source = path.join(bundled, directory);
    if (fs.existsSync(source)) {
      fs.cpSync(source, path.join(runtime, directory), { recursive: true, force: true });
    }
  }
  for (const file of ['run.ps1', 'run.cmd', 'pyproject.toml', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']) {
    const source = path.join(bundled, file);
    if (fs.existsSync(source)) fs.copyFileSync(source, path.join(runtime, file));
  }
  const bundledConfig = path.join(bundled, 'config');
  const runtimeConfig = path.join(runtime, 'config');
  fs.mkdirSync(runtimeConfig, { recursive: true });
  if (fs.existsSync(bundledConfig)) {
    for (const item of fs.readdirSync(bundledConfig)) {
      const destination = path.join(runtimeConfig, item);
      if (!fs.existsSync(destination)) {
        fs.copyFileSync(path.join(bundledConfig, item), destination);
      }
    }
  }
  fs.mkdirSync(path.join(runtime, 'data'), { recursive: true });
  fs.mkdirSync(path.join(runtime, 'reports'), { recursive: true });
  return runtime;
}

function isSafeExternalUrl(rawUrl) {
  try {
    return new URL(rawUrl).protocol === 'https:';
  } catch {
    return false;
  }
}

function hardenSessionContents(contents) {
  contents.on('will-navigate', (event, url) => {
    if (!isAllowedSessionUrl(url)) event.preventDefault();
  });
  contents.setWindowOpenHandler(({ url }) => (
    isAllowedSessionUrl(url)
      ? {
          action: 'allow',
          overrideBrowserWindowOptions: {
            width: 620, height: 760,
            webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
          },
        }
      : { action: 'deny' }
  ));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    title: 'AI Job Search Pipeline',
    icon: path.join(GUI_ROOT, 'build', 'icon.png'),
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-attach-webview', (event, webPreferences, params) => {
    if (!isAllowedSessionUrl(params.src)) {
      event.preventDefault();
      return;
    }
    delete webPreferences.preload;
    webPreferences.nodeIntegration = false;
    webPreferences.contextIsolation = true;
    webPreferences.sandbox = true;
  });
  mainWindow.webContents.on('did-attach-webview', (_event, contents) => {
    hardenSessionContents(contents);
    contents.on('did-create-window', (child) => hardenSessionContents(child.webContents));
  });

  const lockedSessions = [
    session.defaultSession,
    session.fromPartition('persist:ai-job-search-browser'),
  ];
  for (const browserSession of lockedSessions) {
    browserSession.setPermissionRequestHandler(
      (_contents, _permission, callback) => callback(false),
    );
    browserSession.setPermissionCheckHandler(() => false);
  }
  mainWindow.on('closed', () => { mainWindow = null; });

  if (process.env.ELECTRON_DEV === '1') {
    mainWindow.loadURL('http://localhost:7100');
  } else {
    mainWindow.loadFile(path.join(GUI_ROOT, 'dist', 'index.html'));
  }
}

app.setAppUserModelId('com.albertdeluna.aijobsearch');
app.whenReady().then(() => {
  PIPELINE_ROOT = preparePipelineRoot();
  createWindow();
  // Services and searches remain explicit user actions.
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});
app.on('window-all-closed', () => { app.quit(); });

// kill only the child processes this instance spawned (Paperclip node).
// Docker containers and pre-existing services are left running.
app.on('before-quit', () => {
  for (const child of spawnedChildren) {
    try { child.kill(); } catch { /* already gone */ }
  }
});

// ── helpers ─────────────────────────────────────────────────────────────────

// find an executable on PATH (cross-platform; honors PATHEXT on Windows)
function findOnPath(name) {
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  const exts = process.platform === 'win32'
    ? (process.env.PATHEXT || '.EXE;.CMD;.BAT;.COM').split(';')
    : [''];
  for (const dir of dirs) {
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext);
      try {
        if (fs.statSync(candidate).isFile()) return candidate;
      } catch { /* not here */ }
    }
  }
  return null;
}

// PowerShell resolver: powershell.exe on Windows, pwsh elsewhere (PATH).
// Returns null when unavailable — callers must return an error object.
function resolvePowerShell() {
  if (process.platform === 'win32') {
    const full = process.env.SystemRoot
      ? path.join(process.env.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
      : null;
    if (full && fs.existsSync(full)) return full;
    return findOnPath('powershell') || findOnPath('pwsh');
  }
  return findOnPath('pwsh') || findOnPath('powershell');
}

function resolveNode() {
  if (process.env.NODE_EXE) return process.env.NODE_EXE;
  return process.platform === 'win32' ? 'node.exe' : 'node';
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function runPowerShell(args, { onLine } = {}) {
  return new Promise((resolve) => {
    const ps = resolvePowerShell();
    if (!ps) {
      resolve({
        code: -1,
        output: 'PowerShell not found: this feature requires powershell.exe (Windows) or pwsh on PATH (macOS/Linux).',
      });
      return;
    }
    const child = spawn(ps, ['-NoProfile', '-ExecutionPolicy', 'Bypass', ...args], {
      cwd: PIPELINE_ROOT,
      windowsHide: true,
    });
    let out = '';
    let outBuf = '';
    let errBuf = '';
    const flush = (buf, isErr) => {
      const lines = buf.split(/\r?\n/);
      const tail = lines.pop();
      for (const line of lines) {
        out += line + '\n';
        if (onLine) onLine(line, isErr ? 'stderr' : 'stdout');
      }
      return tail;
    };
    child.stdout.on('data', (d) => { outBuf = flush(outBuf + d.toString(), false); });
    child.stderr.on('data', (d) => { errBuf = flush(errBuf + d.toString(), true); });
    child.on('error', (err) => resolve({ code: -1, output: out + String(err) }));
    child.on('close', (code) => {
      if (outBuf) { out += outBuf; if (onLine) onLine(outBuf, 'stdout'); }
      if (errBuf) { out += errBuf; if (onLine) onLine(errBuf, 'stderr'); }
      resolve({ code, output: out });
    });
  });
}

function httpGetJson(url, timeoutMs = 5000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = '';
      res.on('data', (c) => { body += c; });
      res.on('end', () => {
        let json = null;
        try { json = JSON.parse(body); } catch { /* not json */ }
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 400, status: res.statusCode, json, body: body.slice(0, 500) });
      });
    });
    req.on('timeout', () => { req.destroy(new Error('timeout')); });
    req.on('error', (err) => resolve({ ok: false, status: 0, json: null, error: String(err.message || err) }));
  });
}

// ── backend service auto-launch ─────────────────────────────────────────────

const PAPERCLIP_HEALTH = 'http://127.0.0.1:3100/api/health';
const RESUME_MATCHER_HEALTH = 'http://127.0.0.1:3000/';

// Paperclip: multi-agent orchestrator on :3100, run via system Node.
async function startPaperclip() {
  const existing = await httpGetJson(PAPERCLIP_HEALTH, 2000);
  if (existing.ok) {
    return { up: true, spawned: false, alreadyRunning: true, raw: existing.status };
  }
  const entry = path.join(PIPELINE_ROOT, 'node_modules', 'paperclipai', 'dist', 'index.js');
  if (!fs.existsSync(entry)) {
    return { up: false, spawned: false, error: `paperclipai not installed (missing ${entry})` };
  }
  let spawnError = null;
  try {
    const child = spawn(
      resolveNode(),
      [entry, 'run', '--data-dir', path.join(PIPELINE_ROOT, '.paperclip-runtime')],
      {
        cwd: PIPELINE_ROOT,
        env: { ...process.env, PAPERCLIP_TELEMETRY_DISABLED: '1' },
        stdio: 'ignore',
        windowsHide: true,
      },
    );
    child.on('error', (err) => { spawnError = err; spawnedChildren.delete(child); });
    child.on('exit', () => spawnedChildren.delete(child));
    spawnedChildren.add(child);
  } catch (err) {
    return { up: false, spawned: false, error: String(err.message || err) };
  }
  // poll health for up to ~30s
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    await sleep(1500);
    if (spawnError) {
      return { up: false, spawned: false, error: `failed to spawn node: ${String(spawnError.message || spawnError)}` };
    }
    const h = await httpGetJson(PAPERCLIP_HEALTH, 2000);
    if (h.ok) return { up: true, spawned: true };
  }
  return { up: false, spawned: true, error: 'Paperclip spawned but :3100 health check did not pass within 30s' };
}

// run a docker CLI command, resolving to { code, output } instead of throwing
function runDocker(docker, args) {
  return new Promise((resolve) => {
    const child = spawn(docker, args, { cwd: PIPELINE_ROOT, windowsHide: true });
    let out = '';
    child.stdout.on('data', (d) => { out += d.toString(); });
    child.stderr.on('data', (d) => { out += d.toString(); });
    child.on('error', (err) => resolve({ code: -1, output: String(err.message || err) }));
    child.on('close', (code) => resolve({ code, output: out }));
  });
}

// Resume-Matcher: Docker container on :3000. Never kills what we didn't start;
// the container itself is left running on app quit.
async function startResumeMatcher() {
  const existing = await httpGetJson(RESUME_MATCHER_HEALTH, 2000);
  if (existing.ok) {
    return { up: true, spawned: false, alreadyRunning: true, raw: existing.status };
  }
  const docker = findOnPath('docker');
  if (!docker) {
    return { up: false, spawned: false, dockerMissing: true, error: 'docker not found on PATH' };
  }
  let res = await runDocker(docker, ['start', 'ai-job-resume-matcher']);
  if (res.code !== 0) {
    res = await runDocker(docker, [
      'run', '-d', '--name', 'ai-job-resume-matcher',
      '-p', '3000:3000', 'ghcr.io/srbhr/resume-matcher:1.2.0',
    ]);
  }
  if (res.code !== 0) {
    return {
      up: false,
      spawned: false,
      error: (res.output || `docker exited with code ${res.code}`).trim().slice(0, 400),
    };
  }
  // poll health for up to ~45s (image pull / container boot can be slow)
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    await sleep(2000);
    const h = await httpGetJson(RESUME_MATCHER_HEALTH, 2000);
    if (h.ok) return { up: true, spawned: true };
  }
  return { up: false, spawned: true, error: 'container started but :3000 did not respond within 45s' };
}

function readJsonSafe(relPath) {
  const p = path.join(PIPELINE_ROOT, relPath);
  try {
    return { exists: true, data: JSON.parse(fs.readFileSync(p, 'utf8')), path: p };
  } catch (err) {
    if (err.code === 'ENOENT') return { exists: false, data: null, path: p };
    return { exists: true, data: null, path: p, error: String(err.message || err) };
  }
}

function defaultResumePath() {
  const profile = readJsonSafe(path.join('config', 'profile.json'));
  const configuredName = profile.data
    && profile.data.source
    && profile.data.source.resume_file_name
    ? String(profile.data.source.resume_file_name)
    : 'resume.docx';
  const candidates = [
    process.env.JOB_PIPELINE_RESUME,
    path.join(os.homedir(), 'Downloads', configuredName),
    path.join(PIPELINE_ROOT, 'private', 'resume.docx'),
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate)) || '';
}

// Only these config files may be read/written through config:* channels.
const CONFIG_ALLOWLIST = new Set([
  'profile.json',
  'searches.json',
  'access_policy.json',
  'agent_web_browser.json',
]);

function configPath(name) {
  if (!CONFIG_ALLOWLIST.has(name)) throw new Error(`config file not allowed: ${name}`);
  return path.join(PIPELINE_ROOT, 'config', name);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field); field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.length > 1 || row[0] !== '') rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== '' || row.length > 0) { row.push(field); rows.push(row); }
  if (rows.length === 0) return [];
  const header = rows[0];
  return rows.slice(1).map((r) => {
    const obj = {};
    header.forEach((h, idx) => { obj[h] = r[idx] !== undefined ? r[idx] : ''; });
    return obj;
  });
}

// ── IPC handlers ────────────────────────────────────────────────────────────

ipcMain.handle('doctor', async () => {
  const res = await runPowerShell(['-File', path.join(PIPELINE_ROOT, 'run.ps1'), 'doctor']);
  return res;
});

ipcMain.handle('services', async () => {
  const [awb, paperclip, resumeMatcher] = await Promise.all([
    httpGetJson('http://127.0.0.1:7896/health'),
    httpGetJson('http://127.0.0.1:3100/api/health'),
    httpGetJson('http://127.0.0.1:3000/'),
  ]);
  return {
    awb: {
      up: awb.ok,
      app: awb.json && awb.json.app ? awb.json.app : null,
      isBridge: !!(awb.json && awb.json.app === 'Agent Web Browser'),
      raw: awb.error || awb.status,
    },
    paperclip: {
      up: paperclip.ok,
      raw: paperclip.error || paperclip.status,
    },
    resumeMatcher: {
      up: resumeMatcher.ok,
      raw: resumeMatcher.error || resumeMatcher.status,
    },
  };
});

// services:start — (re)attempt to launch one or all backend services.
ipcMain.handle('services:start', async (_e, payload) => {
  const service = payload && payload.service ? String(payload.service) : 'all';
  if (!new Set(['paperclip', 'resume-matcher', 'all']).has(service)) {
    return { error: 'unsupported service: ' + service };
  }
  const result = {};
  if (service === 'paperclip' || service === 'all') {
    result.paperclip = await startPaperclip();
  }
  if (service === 'resume-matcher' || service === 'all') {
    result.resumeMatcher = await startResumeMatcher();
  }
  return result;
});

ipcMain.handle('search:spawn', async (event, args) => {
  try {
    const agentRun = path.join(PIPELINE_ROOT, 'scripts', 'agent-run.ps1');
    const { args: psArgs, safe } = buildPipelineSearchArgs(agentRun, args || {});
    if (!safe.resumePath) {
      throw new Error('Choose the corrected .docx resume before searching.');
    }
    if (safe.resumePath && !fs.existsSync(safe.resumePath)) {
      throw new Error('The selected resume file does not exist.');
    }
    const wc = event.sender;
    const result = await runPowerShell(psArgs, {
      onLine: (line, stream) => {
        if (!wc.isDestroyed()) wc.send('search:log', { line, stream });
      },
    });
    return { ...result, search: safe };
  } catch (err) {
    return {
      code: -1,
      output: 'Search validation failed: ' + String(err.message || err),
    };
  }
});

ipcMain.handle('jobs:read', async () => {
  const p = path.join(PIPELINE_ROOT, 'reports', 'job_matches_verified.csv');
  try {
    const text = fs.readFileSync(p, 'utf8');
    return { exists: true, rows: parseCsv(text), path: p };
  } catch (err) {
    if (err.code === 'ENOENT') return { exists: false, rows: [], path: p };
    return { exists: true, rows: [], path: p, error: String(err.message || err) };
  }
});

ipcMain.handle('report:open', async () => {
  const p = path.join(PIPELINE_ROOT, 'reports', 'job_matches.html');
  const result = await shell.openPath(p);
  return { ok: result === '', error: result || null, path: p };
});

ipcMain.handle('applications:refresh', async () => {
  return runPowerShell(['-File', path.join(PIPELINE_ROOT, 'run.ps1'), 'applications-report']);
});

ipcMain.handle('applications:flag', async (_event, payload) => {
  const identityKey = String(payload && payload.identityKey ? payload.identityKey : '');
  const flag = String(payload && payload.flag ? payload.flag : '');
  if (!/^[0-9a-f]{16}$/.test(identityKey)) {
    return { code: -1, output: 'Invalid application identity.' };
  }
  if (!new Set(['interview', 'denied', 'not_selected']).has(flag)) {
    return { code: -1, output: 'Invalid application outcome flag.' };
  }
  return runPowerShell([
    '-File', path.join(PIPELINE_ROOT, 'run.ps1'),
    'application-flag', identityKey, flag,
  ]);
});

ipcMain.handle('applications:undo', async (_event, payload) => {
  const identityKey = String(payload && payload.identityKey ? payload.identityKey : '');
  if (!/^[0-9a-f]{16}$/.test(identityKey)) {
    return { code: -1, output: 'Invalid application identity.' };
  }
  return runPowerShell([
    '-File', path.join(PIPELINE_ROOT, 'run.ps1'),
    'application-undo', identityKey,
  ]);
});

ipcMain.handle('applications:read', async () => {
  const result = readJsonSafe(path.join('reports', 'applications_dashboard.json'));
  return {
    exists: result.exists,
    summary: result.data && result.data.summary ? result.data.summary : {},
    applications: result.data && Array.isArray(result.data.applications)
      ? result.data.applications
      : [],
    error: result.error || null,
  };
});

ipcMain.handle('applications:report-open', async () => {
  const reportPath = path.join(PIPELINE_ROOT, 'reports', 'applications_dashboard.html');
  const result = await shell.openPath(reportPath);
  return { ok: result === '', error: result || null, path: reportPath };
});

ipcMain.handle('app:info', async () => ({
  packaged: app.isPackaged,
  pipelineRoot: PIPELINE_ROOT,
  defaultQuery: DEFAULT_QUERY,
  defaultLocations: DEFAULT_LOCATIONS,
  defaultResumePath: defaultResumePath(),
}));

ipcMain.handle('resume:pick', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Choose the corrected resume',
    properties: ['openFile'],
    filters: [{ name: 'Word document', extensions: ['docx'] }],
  });
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true, path: '' };
  }
  return { canceled: false, path: result.filePaths[0] };
});

ipcMain.handle('external:open', async (_event, rawUrl) => {
  const url = String(rawUrl || '');
  if (!isSafeExternalUrl(url)) {
    return { ok: false, error: 'Only HTTPS links may be opened externally.' };
  }
  await shell.openExternal(url);
  return { ok: true };
});
ipcMain.handle('agents:list', async () => {
  const base = 'http://127.0.0.1:3100';
  const companiesRes = await httpGetJson(`${base}/api/companies`);
  if (!companiesRes.ok || !companiesRes.json) {
    return { online: false, agents: [], message: 'Paperclip offline — start it with scripts/paperclip-start-local.ps1' };
  }
  const companies = Array.isArray(companiesRes.json) ? companiesRes.json : (companiesRes.json.companies || []);
  const company = companies.find((c) => c && c.name === 'AI Job Search Team') || companies[0];
  if (!company) {
    return { online: true, agents: [], message: 'Paperclip online but company "AI Job Search Team" not found' };
  }
  const agentsRes = await httpGetJson(`${base}/api/companies/${company.id}/agents`);
  if (!agentsRes.ok) {
    return { online: true, agents: [], message: `Failed to list agents (HTTP ${agentsRes.status})`, company: company.name };
  }
  const agents = Array.isArray(agentsRes.json) ? agentsRes.json : (agentsRes.json.agents || []);
  return { online: true, company: company.name, agents };
});

ipcMain.handle('config:read', async (_e, name) => {
  try {
    const p = configPath(name);
    try {
      const text = fs.readFileSync(p, 'utf8');
      return { exists: true, text, path: p };
    } catch (err) {
      if (err.code === 'ENOENT') return { exists: false, text: '', path: p };
      throw err;
    }
  } catch (err) {
    return { exists: false, text: '', error: String(err.message || err) };
  }
});

ipcMain.handle('config:write', async (_e, name, text) => {
  try {
    const p = configPath(name);
    // validate JSON before touching disk
    JSON.parse(text);
    if (fs.existsSync(p)) {
      fs.copyFileSync(p, p + '.bak');
    }
    fs.writeFileSync(p, JSON.stringify(JSON.parse(text), null, 2) + '\n', 'utf8');
    return { ok: true, path: p };
  } catch (err) {
    return { ok: false, error: String(err.message || err) };
  }
});

ipcMain.handle('sessions:read', async () => {
  const res = readJsonSafe(path.join('data', 'site_sessions.json'));
  return { exists: res.exists, data: res.data || {}, error: res.error || null };
});

ipcMain.handle('awb:launch', async () => {
  const exe = path.join(
    PIPELINE_ROOT, 'tools', 'upstream', 'agent-web-browser',
    'src-tauri', 'target', 'release', 'AWB.exe',
  );
  if (!fs.existsSync(exe)) {
    return { launched: false, bridgeUp: false, error: `AWB.exe not found at ${exe}` };
  }
  try {
    const child = spawn(exe, [], { detached: true, stdio: 'ignore', windowsHide: false });
    child.unref();
  } catch (err) {
    return { launched: false, bridgeUp: false, error: String(err.message || err) };
  }
  // give the bridge ~8s to come up
  await new Promise((r) => setTimeout(r, 8000));
  const health = await httpGetJson('http://127.0.0.1:7896/health');
  const appName = health.json && health.json.app ? health.json.app : null;
  return {
    launched: true,
    bridgeUp: health.ok && appName === 'Agent Web Browser',
    app: appName,
    raw: health.error || health.status,
  };
});

// login:open — renderer handles tab opening; main just resolves the URL.
ipcMain.handle('login:url', async (_e, siteKey) => {
  const res = readJsonSafe(path.join('config', 'access_policy.json'));
  const site = res.data && res.data.session_sites && res.data.session_sites[siteKey];
  if (!site || !site.login_url) return { ok: false, error: `no login_url for site "${siteKey}"` };
  const url = String(site.login_url);
  if (!isAllowedSessionUrl(url)) {
    return { ok: false, error: 'configured login URL is outside the reviewed domain allowlist' };
  }
  return { ok: true, url };
});
