'use strict';

const crypto = require('node:crypto');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const START_TIMEOUT_MS = 15000;
const STOP_TIMEOUT_MS = 5000;
const RESPONSE_CAP_BYTES = 2 * 1024 * 1024;
const MAX_PROVIDER_CREDENTIAL_BYTES = 64 * 1024;
const PROVIDER_URL_KEY = 'EXPEDIENT_PROVIDER_URL';
const PROVIDER_KEY_ENV_KEY = 'EXPEDIENT_PROVIDER_KEY_ENV';
const PROVIDER_ENV_NAME_PATTERN = /^[A-Z][A-Z0-9_]{0,71}$/;
const MANAGED_CHILD_ENV = new Set([
  'PYTHONPATH',
  'PYTHONDONTWRITEBYTECODE',
  'EXPEDIENT_CONTROL_TOKEN',
  'EXPEDIENT_DATA_DIR',
  'ONLY_CLI_NODE',
  'ELECTRON_RUN_AS_NODE',
  PROVIDER_URL_KEY,
  PROVIDER_KEY_ENV_KEY,
]);

function validateProviderEnv(value) {
  if (value === undefined) return {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid provider environment.');
  }
  const providerUrl = value[PROVIDER_URL_KEY];
  const credentialEnv = value[PROVIDER_KEY_ENV_KEY];
  if (
    typeof credentialEnv !== 'string'
    || !PROVIDER_ENV_NAME_PATTERN.test(credentialEnv)
    || MANAGED_CHILD_ENV.has(credentialEnv)
  ) {
    throw new Error('Invalid provider environment.');
  }
  const expectedKeys = new Set([PROVIDER_URL_KEY, PROVIDER_KEY_ENV_KEY, credentialEnv]);
  const suppliedKeys = Reflect.ownKeys(value);
  if (expectedKeys.size !== 3 || suppliedKeys.length !== 3
      || suppliedKeys.some((key) => typeof key !== 'string' || !expectedKeys.has(key))) {
    throw new Error('Invalid provider environment.');
  }
  if (
    typeof providerUrl !== 'string'
    || providerUrl !== providerUrl.trim()
    || providerUrl.length > 2048
  ) {
    throw new Error('Invalid provider environment.');
  }
  let parsed;
  try {
    parsed = new URL(providerUrl);
  } catch {
    throw new Error('Invalid provider environment.');
  }
  const loopback = new Set(['127.0.0.1', '[::1]', 'localhost']);
  if (
    parsed.protocol !== 'http:'
    || !loopback.has(parsed.hostname.toLowerCase())
    || parsed.username
    || parsed.password
    || parsed.pathname !== '/v1'
    || parsed.search
    || parsed.hash
  ) {
    throw new Error('Invalid provider environment.');
  }
  const credential = value[credentialEnv];
  if (
    typeof credential !== 'string'
    || !credential.trim()
    || /[\0\r\n]/.test(credential)
    || Buffer.byteLength(credential, 'utf8') > MAX_PROVIDER_CREDENTIAL_BYTES
  ) {
    throw new Error('Invalid provider environment.');
  }
  return {
    [PROVIDER_URL_KEY]: providerUrl,
    [PROVIDER_KEY_ENV_KEY]: credentialEnv,
    [credentialEnv]: credential,
  };
}

function sanitizedChildEnvironment(environment) {
  const sanitized = { ...environment };
  const providerKeys = new Set([
    PROVIDER_URL_KEY,
    PROVIDER_KEY_ENV_KEY,
    'FREECHAIN_ACCESS_KEY',
  ]);
  for (const [key, value] of Object.entries(sanitized)) {
    if (key.toUpperCase() !== PROVIDER_KEY_ENV_KEY || typeof value !== 'string') continue;
    const inheritedCredentialEnv = value.toUpperCase();
    if (PROVIDER_ENV_NAME_PATTERN.test(inheritedCredentialEnv)) {
      providerKeys.add(inheritedCredentialEnv);
    }
  }
  for (const key of Object.keys(sanitized)) {
    if (providerKeys.has(key.toUpperCase())) delete sanitized[key];
  }
  return sanitized;
}

function validateControlPath(value) {
  const text = String(value || '');
  if (!text.startsWith('/v1/') || text.includes('..') || text.includes('://')) {
    throw new Error('Invalid control service path.');
  }
  if (!/^\/v1\/[A-Za-z0-9_./:-]+$/.test(text)) {
    throw new Error('Invalid control service path.');
  }
  return text;
}

function requestJson(port, token, method, requestPath, payload) {
  return new Promise((resolve, reject) => {
    const body = payload === undefined ? null : Buffer.from(JSON.stringify(payload), 'utf8');
    const req = http.request({
      host: '127.0.0.1',
      port,
      path: validateControlPath(requestPath),
      method,
      timeout: 30000,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/json',
        ...(body ? {
          'Content-Type': 'application/json',
          'Content-Length': String(body.length),
        } : {}),
      },
    }, (res) => {
      const chunks = [];
      let size = 0;
      res.on('data', (chunk) => {
        size += chunk.length;
        if (size > RESPONSE_CAP_BYTES) {
          req.destroy(new Error('Control response exceeded the 2 MB cap.'));
          return;
        }
        chunks.push(chunk);
      });
      res.on('end', () => {
        let value = null;
        try {
          value = chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : null;
        } catch {
          reject(new Error('Control service returned invalid JSON.'));
          return;
        }
        if ((res.statusCode || 500) >= 400) {
          reject(new Error(value && value.error ? String(value.error) : `Control request failed with HTTP ${res.statusCode}.`));
          return;
        }
        resolve(value);
      });
    });
    req.on('timeout', () => req.destroy(new Error('Control request timed out.')));
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

class ControlServiceManager {
  constructor({
    spawnImpl = spawn,
    requestImpl = requestJson,
    stopTimeoutMs = STOP_TIMEOUT_MS,
    environment = process.env,
  } = {}) {
    this.spawnImpl = spawnImpl;
    this.requestImpl = requestImpl;
    this.stopTimeoutMs = stopTimeoutMs;
    this.environment = environment;
    this.child = null;
    this.port = 0;
    this.token = '';
    this.startAttempt = null;
    this.stopPromise = null;
    this.restartPromise = null;
    this.blockedChild = null;
  }

  status() {
    return { ready: Boolean(this.child && this.port), port: this.port || null };
  }

  clearOwnedState(child) {
    if (this.child !== child) return;
    this.child = null;
    this.port = 0;
    this.token = '';
  }

  blockStartsUntilExit(child) {
    if (!child || this.blockedChild === child) return;
    this.blockedChild = child;
    const release = () => {
      if (this.blockedChild === child) this.blockedChild = null;
    };
    child.once('exit', release);
    child.once('close', release);
  }

  async start({ pythonExecutable, projectRoot, dataRoot, nodeExecutable, providerEnv }) {
    const validatedProviderEnv = validateProviderEnv(providerEnv);
    if (this.stopPromise) await this.stopPromise;
    if (this.blockedChild) {
      throw new Error('Previous control service has not exited.');
    }
    if (this.child && this.port) return this.status();
    if (this.startAttempt) return this.startAttempt.promise;
    const attempt = {
      child: null,
      cancel: null,
      promise: null,
      settled: false,
    };
    const operation = new Promise((resolve, reject) => {
      const token = crypto.randomBytes(32).toString('base64url');
      const pythonPath = [
        projectRoot,
        path.join(projectRoot, 'python-runtime'),
      ].join(path.delimiter);
      const env = {
        ...sanitizedChildEnvironment(this.environment),
        PYTHONPATH: pythonPath,
        PYTHONDONTWRITEBYTECODE: '1',
        EXPEDIENT_CONTROL_TOKEN: token,
        EXPEDIENT_DATA_DIR: dataRoot,
        ONLY_CLI_NODE: nodeExecutable,
        ELECTRON_RUN_AS_NODE: nodeExecutable === process.execPath ? '1' : this.environment.ELECTRON_RUN_AS_NODE,
        ...validatedProviderEnv,
      };
      const child = this.spawnImpl(
        pythonExecutable,
        [
          '-m', 'job_pipeline.service',
          '--host', '127.0.0.1',
          '--port', '0',
          '--project-root', projectRoot,
          '--data-root', dataRoot,
        ],
        {
          cwd: projectRoot,
          env,
          windowsHide: true,
          stdio: ['ignore', 'pipe', 'pipe'],
        },
      );
      attempt.child = child;
      this.child = child;
      this.token = token;
      let stdoutBuffer = '';
      const finishError = (error) => {
        if (attempt.settled) return;
        attempt.settled = true;
        clearTimeout(timeout);
        this.clearOwnedState(child);
        reject(error);
      };
      attempt.cancel = () => finishError(new Error('Control service start cancelled.'));
      const timeout = setTimeout(() => {
        this.blockStartsUntilExit(child);
        finishError(new Error('Control service did not become ready within 15 seconds.'));
        try { child.kill(); } catch { /* start remains blocked until observed exit */ }
      }, START_TIMEOUT_MS);
      child.stdout.on('data', (chunk) => {
        stdoutBuffer += chunk.toString('utf8');
        const lines = stdoutBuffer.split(/\r?\n/);
        stdoutBuffer = lines.pop() || '';
        for (const line of lines) {
          let record;
          try { record = JSON.parse(line); } catch { continue; }
          if (record.event !== 'expedient_control_ready') continue;
          if (record.host !== '127.0.0.1' || !Number.isInteger(record.port)) {
            this.blockStartsUntilExit(child);
            finishError(new Error('Control service returned an invalid ready record.'));
            try { child.kill(); } catch { /* start remains blocked until observed exit */ }
            return;
          }
          if (attempt.settled || this.child !== child) return;
          attempt.settled = true;
          clearTimeout(timeout);
          this.port = record.port;
          resolve(this.status());
        }
      });
      child.stderr.on('data', () => {
        // Intentionally not forwarded to the renderer. Startup failures surface by exit.
      });
      child.on('error', (error) => finishError(error));
      child.on('exit', (code) => {
        this.clearOwnedState(child);
        if (!attempt.settled) {
          finishError(new Error(`Control service exited before ready with code ${code}.`));
        }
      });
    });
    attempt.promise = operation.finally(() => {
      if (this.startAttempt === attempt) this.startAttempt = null;
    });
    this.startAttempt = attempt;
    return attempt.promise;
  }

  async request(method, requestPath, payload) {
    if (!this.child || !this.port || !this.token) {
      throw new Error('Control service is not ready.');
    }
    return this.requestImpl(
      this.port,
      this.token,
      String(method || 'GET').toUpperCase(),
      validateControlPath(requestPath),
      payload,
    );
  }

  stop() {
    if (this.stopPromise) return this.stopPromise;
    const operation = this.stopOwnedChild();
    const tracked = operation.finally(() => {
      if (this.stopPromise === tracked) this.stopPromise = null;
    });
    this.stopPromise = tracked;
    return tracked;
  }

  async stopOwnedChild() {
    const attempt = this.startAttempt;
    const child = this.child || (attempt && attempt.child) || this.blockedChild;
    const startSettled = attempt && attempt.promise
      ? attempt.promise.catch(() => {})
      : Promise.resolve();
    if (attempt && attempt.cancel) attempt.cancel();
    this.clearOwnedState(child);
    if (!child) {
      await startSettled;
      return;
    }
    if (child.exitCode !== undefined && child.exitCode !== null) {
      if (this.blockedChild === child) this.blockedChild = null;
      await startSettled;
      return;
    }

    let onExit;
    const exited = new Promise((resolve) => {
      onExit = () => resolve(true);
      child.once('exit', onExit);
      child.once('close', onExit);
    });
    try {
      child.kill();
    } catch {
      child.removeListener('exit', onExit);
      child.removeListener('close', onExit);
      this.blockStartsUntilExit(child);
      await startSettled;
      throw new Error('Control service could not be stopped.');
    }
    let timeout;
    const stopped = await Promise.race([
      exited,
      new Promise((resolve) => {
        timeout = setTimeout(() => resolve(false), this.stopTimeoutMs);
      }),
    ]);
    clearTimeout(timeout);
    child.removeListener('exit', onExit);
    child.removeListener('close', onExit);
    await startSettled;
    if (!stopped) {
      this.blockStartsUntilExit(child);
      throw new Error('Control service did not exit before the stop timeout.');
    }
    if (this.blockedChild === child) this.blockedChild = null;
  }

  restart(options) {
    const prior = this.restartPromise;
    const operation = (prior ? prior.catch(() => {}) : Promise.resolve()).then(async () => {
      await this.stop();
      return this.start(options);
    });
    const tracked = operation.finally(() => {
      if (this.restartPromise === tracked) this.restartPromise = null;
    });
    this.restartPromise = tracked;
    return tracked;
  }
}

function packagedPipelineRoot(resourcesPath) {
  return path.join(resourcesPath, 'pipeline');
}

module.exports = {
  ControlServiceManager,
  packagedPipelineRoot,
  requestJson,
  validateControlPath,
};
