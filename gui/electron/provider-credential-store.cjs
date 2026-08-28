'use strict';

const fs = require('node:fs');
const path = require('node:path');

const PROVIDER = 'FreeChain';
const RECORD_VERSION = 1;
const RECORD_NAME = 'provider-credential.json';
const MAX_ENV_FILE_BYTES = 64 * 1024;
const MAX_CREDENTIAL_BYTES = 64 * 1024;
const MAX_RECORD_BYTES = 128 * 1024;
const SAFE_SOURCES = new Set([
  'environment',
  'configured file',
  'FreeChain file',
  'saved',
  'unavailable',
]);

function normalizeCredential(value) {
  if (typeof value !== 'string') return null;
  let credential = value.trim();
  if (
    credential.length >= 2
    && ((credential.startsWith('"') && credential.endsWith('"'))
      || (credential.startsWith("'") && credential.endsWith("'")))
  ) {
    credential = credential.slice(1, -1);
  }
  if (
    !credential
    || /[\0\r\n]/.test(credential)
    || Buffer.byteLength(credential, 'utf8') > MAX_CREDENTIAL_BYTES
  ) return null;
  return credential;
}

function credentialFromEnvFile(filePath, fileSystem = fs) {
  if (typeof filePath !== 'string' || !path.isAbsolute(filePath)) return null;
  try {
    const stat = fileSystem.lstatSync(filePath);
    if (!stat.isFile() || stat.size > MAX_ENV_FILE_BYTES) return null;
    const contents = fileSystem.readFileSync(filePath);
    if (contents.length > MAX_ENV_FILE_BYTES) return null;
    const matches = [];
    for (const line of contents.toString('utf8').replace(/^\uFEFF/, '').split(/\r?\n/)) {
      const match = line.match(/^\s*FREECHAIN_ACCESS_KEY\s*=\s*(.*?)\s*$/);
      if (match) matches.push(match[1]);
    }
    if (matches.length !== 1) return null;
    return normalizeCredential(matches[0]);
  } catch {
    return null;
  }
}

function isCanonicalBase64(value) {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= MAX_RECORD_BYTES
    && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value);
}

class ProviderCredentialStore {
  constructor({ userDataPath, safeStorage, environment = process.env, fileSystem = fs }) {
    if (typeof userDataPath !== 'string' || !path.isAbsolute(userDataPath)) {
      throw new TypeError('userDataPath must be absolute.');
    }
    this.userDataPath = userDataPath;
    this.recordPath = path.join(userDataPath, RECORD_NAME);
    this.safeStorage = safeStorage;
    this.environment = environment && typeof environment === 'object' ? environment : {};
    this.fileSystem = fileSystem;
    this.currentCredential = null;
    this.currentSource = 'unavailable';
    this.savedCredential = false;
    this.loadSavedCredential();
  }

  encryptionAvailable() {
    try {
      return Boolean(
        this.safeStorage
        && typeof this.safeStorage.isEncryptionAvailable === 'function'
        && this.safeStorage.isEncryptionAvailable(),
      );
    } catch {
      return false;
    }
  }

  setUnavailable() {
    this.currentCredential = null;
    this.currentSource = 'unavailable';
    this.savedCredential = false;
  }

  loadSavedCredential() {
    this.setUnavailable();
    if (!this.encryptionAvailable()) return;
    try {
      const stat = this.fileSystem.lstatSync(this.recordPath);
      if (!stat.isFile() || stat.size > MAX_RECORD_BYTES) return;
      const contents = this.fileSystem.readFileSync(this.recordPath);
      if (contents.length > MAX_RECORD_BYTES) return;
      const record = JSON.parse(contents.toString('utf8'));
      if (
        !record
        || record.version !== RECORD_VERSION
        || record.provider !== PROVIDER
        || !isCanonicalBase64(record.ciphertext)
        || typeof record.updatedAt !== 'string'
      ) return;
      const decrypted = this.safeStorage.decryptString(Buffer.from(record.ciphertext, 'base64'));
      const credential = normalizeCredential(decrypted);
      if (!credential) return;
      this.currentCredential = credential;
      this.currentSource = 'saved';
      this.savedCredential = true;
    } catch {
      this.setUnavailable();
    }
  }

  importCandidate() {
    const environmentCredential = normalizeCredential(this.environment.FREECHAIN_ACCESS_KEY);
    if (environmentCredential) {
      return { credential: environmentCredential, source: 'environment' };
    }

    const configuredPath = this.environment.EXPEDIENT_FREECHAIN_ENV_FILE;
    const configuredCredential = credentialFromEnvFile(configuredPath, this.fileSystem);
    if (configuredCredential) {
      return { credential: configuredCredential, source: 'configured file' };
    }

    const localAppData = this.environment.LOCALAPPDATA;
    if (typeof localAppData === 'string' && path.isAbsolute(localAppData)) {
      const installedPath = path.join(localAppData, 'FreeChain', '.env');
      if (
        typeof configuredPath !== 'string'
        || path.resolve(configuredPath) !== path.resolve(installedPath)
      ) {
        const installedCredential = credentialFromEnvFile(installedPath, this.fileSystem);
        if (installedCredential) {
          return { credential: installedCredential, source: 'FreeChain file' };
        }
      }
    }
    return null;
  }

  persist(credential, source) {
    if (!this.encryptionAvailable()) {
      this.setUnavailable();
      return this.status();
    }
    const priorState = {
      credential: this.currentCredential,
      source: this.currentSource,
      saved: this.savedCredential,
    };
    let temporaryPath = null;
    try {
      const ciphertext = this.safeStorage.encryptString(credential);
      if (!Buffer.isBuffer(ciphertext) || ciphertext.length === 0) throw new Error('encryption failed');
      const record = {
        version: RECORD_VERSION,
        provider: PROVIDER,
        ciphertext: ciphertext.toString('base64'),
        updatedAt: new Date().toISOString(),
      };
      this.fileSystem.mkdirSync(this.userDataPath, { recursive: true });
      temporaryPath = `${this.recordPath}.${process.pid}.${Date.now()}.tmp`;
      this.fileSystem.writeFileSync(
        temporaryPath,
        `${JSON.stringify(record)}\n`,
        { encoding: 'utf8', mode: 0o600 },
      );
      this.fileSystem.renameSync(temporaryPath, this.recordPath);
      temporaryPath = null;
      this.currentCredential = credential;
      this.currentSource = SAFE_SOURCES.has(source) ? source : 'unavailable';
      this.savedCredential = true;
      return this.status();
    } catch {
      if (temporaryPath) {
        try { this.fileSystem.rmSync(temporaryPath, { force: true }); } catch { /* best effort */ }
      }
      if (priorState.saved && priorState.credential) {
        this.currentCredential = priorState.credential;
        this.currentSource = priorState.source;
        this.savedCredential = true;
      } else {
        this.setUnavailable();
      }
      return this.status();
    }
  }

  importFromEnvironment() {
    if (!this.encryptionAvailable()) {
      return this.status();
    }
    const candidate = this.importCandidate();
    if (!candidate) {
      return this.status();
    }
    return this.persist(candidate.credential, candidate.source);
  }

  reimportFromEnvironment() {
    return this.importFromEnvironment();
  }

  credential() {
    return this.currentCredential;
  }

  saved() {
    return this.savedCredential;
  }

  status() {
    return {
      available: Boolean(this.currentCredential),
      source: SAFE_SOURCES.has(this.currentSource) ? this.currentSource : 'unavailable',
    };
  }

  clear() {
    try {
      this.fileSystem.rmSync(this.recordPath);
    } catch (error) {
      if (!error || error.code !== 'ENOENT') return false;
    }
    this.setUnavailable();
    return true;
  }
}

module.exports = {
  ProviderCredentialStore,
};
