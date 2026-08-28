'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const {
  ControlServiceManager,
  validateControlPath,
} = require('./control-service.cjs');

test('control paths stay inside the fixed versioned API', () => {
  assert.equal(validateControlPath('/v1/conversations/abc/messages'), '/v1/conversations/abc/messages');
  assert.throws(() => validateControlPath('http://outside.example/v1/health'), /path/);
  assert.throws(() => validateControlPath('/v1/../secrets'), /path/);
  assert.throws(() => validateControlPath('/admin'), /path/);
});

test('manager keeps bearer token out of public status and kills its child', async () => {
  let captured = null;
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.killedByTest = false;
  child.kill = () => {
    child.killedByTest = true;
    process.nextTick(() => child.emit('exit', 0));
  };
  const spawnImpl = (command, args, options) => {
    captured = { command, args, options };
    process.nextTick(() => {
      child.stdout.write('{"event":"expedient_control_ready","host":"127.0.0.1","port":32123}\n');
    });
    return child;
  };
  const requests = [];
  const requestImpl = async (port, token, method, path, payload) => {
    requests.push({ port, token, method, path, payload });
    return { ok: true };
  };
  const manager = new ControlServiceManager({ spawnImpl, requestImpl });
  const status = await manager.start({
    pythonExecutable: 'python-test',
    projectRoot: 'C:\\app\\pipeline',
    dataRoot: 'C:\\app\\data',
    nodeExecutable: 'C:\\app\\electron.exe',
  });

  assert.deepEqual(status, { ready: true, port: 32123 });
  assert.ok(captured.options.env.EXPEDIENT_CONTROL_TOKEN);
  assert.equal(
    captured.options.env.PYTHONPATH,
    ['C:\\app\\pipeline', 'C:\\app\\pipeline\\python-runtime'].join(require('node:path').delimiter),
  );
  assert.equal(captured.options.env.PYTHONDONTWRITEBYTECODE, '1');
  assert.equal(JSON.stringify(status).includes(captured.options.env.EXPEDIENT_CONTROL_TOKEN), false);
  await manager.request('GET', '/v1/health');
  assert.equal(requests[0].token, captured.options.env.EXPEDIENT_CONTROL_TOKEN);
  await manager.stop();
  assert.equal(child.killedByTest, true);
});

test('manager passes the supplied provider environment only to its owned child', async () => {
  let captured = null;
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = () => process.nextTick(() => child.emit('exit', 0));
  const providerEnv = {
    EXPEDIENT_PROVIDER_URL: 'http://127.0.0.1:4853/v1',
    EXPEDIENT_PROVIDER_KEY_ENV: 'TEST_FREECHAIN_ACCESS_KEY',
    TEST_FREECHAIN_ACCESS_KEY: 'synthetic-provider-key',
  };
  const parentProviderEnv = Object.fromEntries(
    Object.keys(providerEnv).map((name) => [name, process.env[name]]),
  );
  const providerKey = providerEnv.TEST_FREECHAIN_ACCESS_KEY;
  const manager = new ControlServiceManager({
    spawnImpl: (_command, _args, options) => {
      assert.deepEqual(
        Object.fromEntries(Object.keys(providerEnv).map((name) => [name, process.env[name]])),
        parentProviderEnv,
      );
      captured = options;
      process.nextTick(() => {
        child.stdout.write('{"event":"expedient_control_ready","host":"127.0.0.1","port":32124}\n');
      });
      return child;
    },
  });

  const status = await manager.start({
    pythonExecutable: 'python-test',
    projectRoot: 'C:\\app\\pipeline',
    dataRoot: 'C:\\app\\data',
    nodeExecutable: 'C:\\app\\electron.exe',
    providerEnv,
  });

  assert.deepEqual(
    Object.fromEntries(Object.keys(providerEnv).map((name) => [name, captured.env[name]])),
    providerEnv,
  );
  assert.deepEqual(
    Object.fromEntries(Object.keys(providerEnv).map((name) => [name, process.env[name]])),
    parentProviderEnv,
  );
  assert.equal(JSON.stringify(status).includes(providerKey), false);
  assert.equal(JSON.stringify(status).includes(providerEnv.EXPEDIENT_PROVIDER_URL), false);
  assert.equal(JSON.stringify(manager.status()).includes(providerKey), false);
  assert.equal(JSON.stringify(manager.status()).includes(providerEnv.EXPEDIENT_PROVIDER_URL), false);
  await manager.stop();
});

test('manager strips ambient provider values when provider environment is omitted', async () => {
  let captured = null;
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = () => process.nextTick(() => child.emit('exit', 0));
  const environment = {
    EXPEDIENT_PROVIDER_URL: 'http://public.example/v1',
    EXPEDIENT_PROVIDER_KEY_ENV: 'AMBIENT_PROVIDER_ACCESS_KEY',
    FREECHAIN_ACCESS_KEY: 'synthetic-fixed-ambient-key',
    AMBIENT_PROVIDER_ACCESS_KEY: 'synthetic-selected-ambient-key',
    UNRELATED_AMBIENT_SETTING: 'preserved',
  };
  const originalEnvironment = { ...environment };
  const manager = new ControlServiceManager({
    environment,
    spawnImpl: (_command, _args, options) => {
      captured = options.env;
      process.nextTick(() => {
        child.stdout.write('{"event":"expedient_control_ready","host":"127.0.0.1","port":32127}\n');
      });
      return child;
    },
  });

  const status = await manager.start({
    pythonExecutable: 'python-test',
    projectRoot: 'C:\\app\\pipeline',
    dataRoot: 'C:\\app\\data',
    nodeExecutable: 'C:\\app\\electron.exe',
  });

  for (const name of [
    'EXPEDIENT_PROVIDER_URL',
    'EXPEDIENT_PROVIDER_KEY_ENV',
    'FREECHAIN_ACCESS_KEY',
    'AMBIENT_PROVIDER_ACCESS_KEY',
  ]) {
    assert.equal(Object.hasOwn(captured, name), false);
  }
  assert.equal(captured.UNRELATED_AMBIENT_SETTING, 'preserved');
  assert.deepEqual(environment, originalEnvironment);
  assert.equal(JSON.stringify(status).includes('synthetic-selected-ambient-key'), false);
  await manager.stop();
});

test('manager removes mixed-case ambient aliases before explicit provider values win', async () => {
  let captured = null;
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = () => process.nextTick(() => child.emit('exit', 0));
  const environment = {
    eXpEdIeNt_PrOvIdEr_Url: 'http://public.example/v1',
    ExPeDiEnT_pRoViDeR_kEy_EnV: 'MiXeD_Ambient_Access_Key',
    fReEcHaIn_AcCeSs_KeY: 'synthetic-fixed-ambient-key',
    mIxEd_aMbIeNt_aCcEsS_kEy: 'synthetic-selected-ambient-key',
    Unrelated_Ambient_Setting: 'preserved exactly',
  };
  const originalEnvironment = { ...environment };
  const providerEnv = {
    EXPEDIENT_PROVIDER_URL: 'http://127.0.0.1:4853/v1',
    EXPEDIENT_PROVIDER_KEY_ENV: 'FREECHAIN_ACCESS_KEY',
    FREECHAIN_ACCESS_KEY: 'synthetic-explicit-key',
  };
  const manager = new ControlServiceManager({
    environment,
    spawnImpl: (_command, _args, options) => {
      captured = options.env;
      process.nextTick(() => {
        child.stdout.write('{"event":"expedient_control_ready","host":"127.0.0.1","port":32128}\n');
      });
      return child;
    },
  });

  await manager.start({
    pythonExecutable: 'python-test',
    projectRoot: 'C:\\app\\pipeline',
    dataRoot: 'C:\\app\\data',
    nodeExecutable: 'C:\\app\\electron.exe',
    providerEnv,
  });

  const providerNames = new Set([
    'EXPEDIENT_PROVIDER_URL',
    'EXPEDIENT_PROVIDER_KEY_ENV',
    'FREECHAIN_ACCESS_KEY',
    'MIXED_AMBIENT_ACCESS_KEY',
  ]);
  assert.deepEqual(
    Object.fromEntries(
      Object.entries(captured).filter(([name]) => providerNames.has(name.toUpperCase())),
    ),
    providerEnv,
  );
  assert.equal(captured.Unrelated_Ambient_Setting, 'preserved exactly');
  assert.deepEqual(environment, originalEnvironment);
  await manager.stop();
});

test('manager rejects malformed provider environments before spawning', async () => {
  let spawnCount = 0;
  const manager = new ControlServiceManager({
    spawnImpl: () => {
      spawnCount += 1;
      throw new Error('spawn must not run');
    },
  });
  const base = {
    EXPEDIENT_PROVIDER_URL: 'http://127.0.0.1:4853/v1',
    EXPEDIENT_PROVIDER_KEY_ENV: 'TEST_FREECHAIN_ACCESS_KEY',
    TEST_FREECHAIN_ACCESS_KEY: 'synthetic-provider-key',
  };
  const invalidEnvironments = [
    { ...base, UNKNOWN_PROVIDER_OPTION: 'nope' },
    { ...base, [Symbol('unknown provider option')]: 'nope' },
    { ...base, EXPEDIENT_PROVIDER_URL: 'http://public.example/v1' },
    { ...base, EXPEDIENT_PROVIDER_URL: 'https://127.0.0.1:4853/v1' },
    { ...base, EXPEDIENT_PROVIDER_URL: 'http://127.0.0.1:4853/v1/models' },
    { ...base, EXPEDIENT_PROVIDER_KEY_ENV: 'lowercase_name' },
    { ...base, TEST_FREECHAIN_ACCESS_KEY: '' },
    { ...base, TEST_FREECHAIN_ACCESS_KEY: 'x'.repeat((64 * 1024) + 1) },
  ];
  const options = {
    pythonExecutable: 'python-test',
    projectRoot: 'C:\\app\\pipeline',
    dataRoot: 'C:\\app\\data',
    nodeExecutable: 'C:\\app\\electron.exe',
  };

  for (const providerEnv of invalidEnvironments) {
    await assert.rejects(manager.start({ ...options, providerEnv }), /provider environment/i);
  }
  assert.equal(spawnCount, 0);
});

test('restart cancels an in-flight start and waits for exit before spawning one replacement', async () => {
  const events = [];
  const children = [];
  const makeChild = (number) => {
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.kill = () => {
      events.push(`kill-${number}`);
      if (number === 1) {
        process.nextTick(() => {
          events.push('exit-1');
          child.emit('exit', 0);
        });
      } else {
        process.nextTick(() => child.emit('exit', 0));
      }
    };
    return child;
  };
  const manager = new ControlServiceManager({
    spawnImpl: () => {
      const number = children.length + 1;
      if (number === 2) assert.deepEqual(events, ['spawn-1', 'kill-1', 'exit-1']);
      const child = makeChild(number);
      children.push(child);
      events.push(`spawn-${number}`);
      if (number === 2) {
        process.nextTick(() => {
          child.stdout.write('{"event":"expedient_control_ready","host":"127.0.0.1","port":32125}\n');
        });
      }
      return child;
    },
  });
  const options = {
    pythonExecutable: 'python-test',
    projectRoot: 'C:\\app\\pipeline',
    dataRoot: 'C:\\app\\data',
    nodeExecutable: 'C:\\app\\electron.exe',
  };

  const firstStartOutcome = manager.start(options).catch((error) => error);
  const restarted = await manager.restart(options);

  assert.match((await firstStartOutcome).message, /cancelled/i);
  assert.deepEqual(restarted, { ready: true, port: 32125 });
  assert.equal(children.length, 2);
  assert.deepEqual(events, ['spawn-1', 'kill-1', 'exit-1', 'spawn-2']);
  children[0].emit('exit', 0);
  assert.deepEqual(manager.status(), { ready: true, port: 32125 });
  await manager.stop();
});

test('restart times out safely without overlapping a child that does not exit', async () => {
  let spawnCount = 0;
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = () => {};
  const manager = new ControlServiceManager({
    stopTimeoutMs: 10,
    spawnImpl: () => {
      spawnCount += 1;
      process.nextTick(() => {
        child.stdout.write('{"event":"expedient_control_ready","host":"127.0.0.1","port":32126}\n');
      });
      return child;
    },
  });
  const options = {
    pythonExecutable: 'python-test',
    projectRoot: 'C:\\app\\pipeline',
    dataRoot: 'C:\\app\\data',
    nodeExecutable: 'C:\\app\\electron.exe',
  };

  await manager.start(options);
  await assert.rejects(manager.restart(options), /did not exit/i);

  assert.equal(spawnCount, 1);
  assert.deepEqual(manager.status(), { ready: false, port: null });
});
