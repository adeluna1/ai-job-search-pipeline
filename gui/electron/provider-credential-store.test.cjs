'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { ProviderCredentialStore } = require('./provider-credential-store.cjs');

function fakeSafeStorage() {
  const encrypted = new Map();
  const calls = { encrypt: [], decrypt: [] };
  let sequence = 0;
  return {
    calls,
    isEncryptionAvailable: () => true,
    encryptString: (value) => {
      calls.encrypt.push(value);
      const ciphertext = Buffer.from(`opaque-ciphertext-${++sequence}`, 'utf8');
      encrypted.set(ciphertext.toString('base64'), value);
      return ciphertext;
    },
    decryptString: (value) => {
      calls.decrypt.push(Buffer.from(value));
      const plaintext = encrypted.get(Buffer.from(value).toString('base64'));
      if (!plaintext) throw new Error('ciphertext is invalid');
      return plaintext;
    },
  };
}

test('persists only encrypted provider credentials across imports, restarts, and clearing', () => {
  const userDataPath = fs.mkdtempSync(path.join(os.tmpdir(), 'expedient-provider-credential-'));
  const environment = { FREECHAIN_ACCESS_KEY: 'synthetic-provider-key-one' };
  const initialCredential = environment.FREECHAIN_ACCESS_KEY;
  const safeStorage = fakeSafeStorage();
  const options = { userDataPath, safeStorage, environment };

  try {
    const store = new ProviderCredentialStore(options);
    assert.equal(store.clear(), true);
    const imported = store.importFromEnvironment();
    const persistedPath = path.join(userDataPath, 'provider-credential.json');
    const persisted = fs.readFileSync(persistedPath, 'utf8');

    assert.deepEqual(imported, { available: true, source: 'environment' });
    assert.deepEqual(safeStorage.calls.encrypt, [environment.FREECHAIN_ACCESS_KEY]);
    const priorCiphertext = JSON.parse(persisted).ciphertext;
    assert.equal(persisted.includes(initialCredential), false);
    assert.match(persisted, /ciphertext/);
    assert.equal(JSON.stringify(store.status()).includes(environment.FREECHAIN_ACCESS_KEY), false);

    const restartedStore = new ProviderCredentialStore(options);
    assert.equal(restartedStore.credential(), environment.FREECHAIN_ACCESS_KEY);

    environment.FREECHAIN_ACCESS_KEY = 'synthetic-provider-key-two';
    const replacementCredential = environment.FREECHAIN_ACCESS_KEY;
    assert.deepEqual(store.reimportFromEnvironment(), { available: true, source: 'environment' });
    assert.deepEqual(safeStorage.calls.encrypt, ['synthetic-provider-key-one', 'synthetic-provider-key-two']);
    assert.equal(new ProviderCredentialStore(options).credential(), environment.FREECHAIN_ACCESS_KEY);
    const replacedPersisted = fs.readFileSync(persistedPath, 'utf8');
    assert.equal(replacedPersisted.includes(initialCredential), false);
    assert.equal(replacedPersisted.includes(replacementCredential), false);
    assert.equal(replacedPersisted.includes(priorCiphertext), false);

    fs.writeFileSync(persistedPath, '{"version":1,"provider":"FreeChain","ciphertext":"corrupt"}', 'utf8');
    const corruptStore = new ProviderCredentialStore(options);
    assert.equal(corruptStore.credential(), null);
    assert.deepEqual(corruptStore.status(), { available: false, source: 'unavailable' });

    assert.equal(store.clear(), true);
    assert.equal(fs.existsSync(persistedPath), false);
    assert.deepEqual(store.status(), { available: false, source: 'unavailable' });

    assert.deepEqual(store.reimportFromEnvironment(), { available: true, source: 'environment' });
    assert.equal(new ProviderCredentialStore(options).credential(), environment.FREECHAIN_ACCESS_KEY);
    assert.ok(safeStorage.calls.decrypt.length >= 3);
  } finally {
    fs.rmSync(userDataPath, { recursive: true, force: true });
  }
});

test('clear preserves truthful state when encrypted record deletion fails', () => {
  const userDataPath = fs.mkdtempSync(path.join(os.tmpdir(), 'expedient-provider-clear-failure-'));
  const environment = { FREECHAIN_ACCESS_KEY: 'synthetic-provider-key' };
  const safeStorage = fakeSafeStorage();
  const persistedPath = path.join(userDataPath, 'provider-credential.json');
  const fileSystem = {
    ...fs,
    rmSync: (target, options) => {
      if (target === persistedPath) {
        const error = new Error('synthetic deletion failure');
        error.code = 'EACCES';
        throw error;
      }
      return fs.rmSync(target, options);
    },
  };
  const store = new ProviderCredentialStore({
    userDataPath,
    safeStorage,
    environment,
    fileSystem,
  });

  try {
    store.importFromEnvironment();
    const beforeClear = fs.readFileSync(persistedPath, 'utf8');

    assert.equal(store.clear(), false);
    assert.equal(fs.readFileSync(persistedPath, 'utf8'), beforeClear);
    assert.equal(store.credential(), environment.FREECHAIN_ACCESS_KEY);
    assert.equal(store.saved(), true);
    assert.deepEqual(store.status(), { available: true, source: 'environment' });
  } finally {
    fs.rmSync(userDataPath, { recursive: true, force: true });
  }
});

test('failed re-import keeps the existing encrypted credential visible and clearable', () => {
  const userDataPath = fs.mkdtempSync(path.join(os.tmpdir(), 'expedient-provider-reimport-failure-'));
  const environment = { FREECHAIN_ACCESS_KEY: 'synthetic-provider-key' };
  const safeStorage = fakeSafeStorage();
  const store = new ProviderCredentialStore({ userDataPath, safeStorage, environment });

  try {
    store.importFromEnvironment();
    delete environment.FREECHAIN_ACCESS_KEY;

    assert.deepEqual(store.reimportFromEnvironment(), { available: true, source: 'environment' });
    assert.equal(store.saved(), true);
    assert.equal(store.credential(), 'synthetic-provider-key');
    assert.equal(store.clear(), true);
    assert.equal(store.saved(), false);
  } finally {
    fs.rmSync(userDataPath, { recursive: true, force: true });
  }
});

test('failed replacement persistence retains the prior encrypted credential state', () => {
  const userDataPath = fs.mkdtempSync(path.join(os.tmpdir(), 'expedient-provider-replacement-failure-'));
  const environment = { FREECHAIN_ACCESS_KEY: 'synthetic-provider-key-one' };
  const safeStorage = fakeSafeStorage();
  let renameCalls = 0;
  const fileSystem = {
    ...fs,
    renameSync: (source, destination) => {
      renameCalls += 1;
      if (renameCalls === 2) throw new Error('synthetic replacement failure');
      return fs.renameSync(source, destination);
    },
  };
  const store = new ProviderCredentialStore({
    userDataPath,
    safeStorage,
    environment,
    fileSystem,
  });

  try {
    store.importFromEnvironment();
    const persistedPath = path.join(userDataPath, 'provider-credential.json');
    const priorRecord = fs.readFileSync(persistedPath, 'utf8');
    environment.FREECHAIN_ACCESS_KEY = 'synthetic-provider-key-two';

    assert.deepEqual(store.reimportFromEnvironment(), { available: true, source: 'environment' });
    assert.equal(store.saved(), true);
    assert.equal(store.credential(), 'synthetic-provider-key-one');
    assert.equal(fs.readFileSync(persistedPath, 'utf8'), priorRecord);
    assert.equal(store.clear(), true);
  } finally {
    fs.rmSync(userDataPath, { recursive: true, force: true });
  }
});
