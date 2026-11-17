// The relay in workerd (Miniflare), with real WebSockets: protocol 1 (Parasite <= 2.10,
// Lust), protocol 2 (Parasite 2.11+, from Rose 1.5.7's relay tests) and rooms with both.
// Run: npm test (from parasite/relay)
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { Miniflare } from 'miniflare';
import WebSocket from 'ws';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));
const temporary = await mkdtemp(join(tmpdir(), 'parasite-relay-test-'));
const bundle = join(temporary, 'bundle');
let worker;

function startWorker() {
  return new Miniflare({
    modules: true,
    scriptPath: join(bundle, 'index.js'),
    modulesRoot: bundle,
    compatibilityDate: '2025-01-01',
    durableObjects: {
      ROOM: { className: 'PartyRoom', useSQLite: true },
      DIRECTORY: { className: 'FriendsDirectory', useSQLite: true },
    },
    durableObjectsPersist: join(temporary, 'rooms'),
  });
}

before(() => {
  execFileSync(process.execPath, [
    require.resolve('wrangler/bin/wrangler.js'), 'deploy', '--dry-run', '--outdir', bundle,
  ], { cwd: root, env: { ...process.env, WRANGLER_SEND_METRICS: 'false' }, stdio: 'pipe' });
  worker = startWorker();
});

after(async () => {
  try {
    await worker?.dispose();
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

const newRoom = () => randomBytes(16).toString('hex');
const credential = (byte) => byte.repeat(64);

function open(url, headers) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url, { headers, handshakeTimeout: 3000 });
    const peer = listen(socket);
    let responseHeaders;
    socket.once('upgrade', (response) => { responseHeaders = response.headers; });
    socket.once('open', () => resolve({ status: 101, headers: responseHeaders, peer }));
    socket.once('unexpected-response', (_request, response) => {
      response.resume();
      response.once('end', () => {
        resolve({ status: response.statusCode, headers: response.headers, peer: null });
        socket.terminate();
      });
      response.once('error', reject);
    });
    socket.on('error', reject);
  });
}

// Parasite 2.11 (party/network/ws_relay.py): p=2, identity in X-Parasite-* headers
async function upgrade(room, id, secret, options = {}) {
  const { path = '/room', protocol = '2', name = 'Lótus 🌹', prefix = 'X-Parasite-', version = '2.11' } = options;
  const url = new URL(path, await worker.ready);
  url.protocol = 'ws:';
  url.search = new URLSearchParams({ key: room, v: version, p: protocol });
  const headers = {};
  if (id !== undefined) headers[prefix + 'Summoner-Id'] = id;
  if (secret !== undefined) headers.Authorization = 'Bearer ' + secret;
  headers[prefix + 'Summoner-Name'] = encodeURIComponent(name);
  return open(url, headers);
}

// Parasite <= 2.10 and Lust: no p, no headers, a join message
async function legacy(room, id, options = {}) {
  const { version = '2.10', name = 'Legacy' + id, join: send = true } = options;
  const url = new URL('/room', await worker.ready);
  url.protocol = 'ws:';
  url.search = new URLSearchParams({ key: room, v: version });
  const response = await open(url, {});
  if (response.status === 101 && send) {
    response.peer.socket.send(JSON.stringify({ type: 'join', summoner_id: id, summoner_name: name }));
  }
  return response;
}

function close(peer) {
  return new Promise((resolve) => {
    if (peer.socket.readyState === WebSocket.CLOSED) return resolve();
    peer.socket.once('close', resolve);
    peer.socket.close(1000);
  });
}

function connect(response, header = 'x-parasite-party-protocol') {
  assert.equal(response.status, 101);
  assert.equal(response.headers[header], '2');
  return response.peer;
}

function listen(socket) {
  const messages = [];
  let wake;
  socket.on('message', (data) => {
    const message = data.toString();
    if (message === 'pong') return;
    messages.push({ raw: message, ...JSON.parse(message) });
    wake?.();
  });
  return {
    socket,
    async next(type, until = () => true) {
      while (true) {
        const index = messages.findIndex((message) => message.type === type && until(message));
        if (index !== -1) return messages.splice(index, 1)[0];
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('Missing message: ' + type)), 2000);
          wake = () => {
            clearTimeout(timeout);
            wake = undefined;
            resolve();
          };
        });
      }
    },
  };
}

const ids = (members) => members.map((member) => member.summoner_id).sort();

// ─── Protocol 1 ──────────────────────────────────────────────────────────────

test('protocol 1: players join with a message and see each other\'s pick', async () => {
  const room = 'lobby' + newRoom().slice(0, 20); // protocol 1 keys need not be hex
  const a = (await legacy(room, 1)).peer;
  assert.deepEqual((await a.next('members')).members, []);
  a.socket.send(JSON.stringify({ type: 'skin', skin: { champion_id: 103, skin_id: 103001 } }));
  const b = (await legacy(room, 2, { version: '1.4.9.90' })).peer; // Lust
  const { members } = await b.next('members', (m) => m.members.length === 2 && m.members.some((x) => x.skin));
  assert.deepEqual(members.find((m) => m.summoner_id === 1).skin, { champion_id: 103, skin_id: 103001 });
  assert.equal(typeof members[0].summoner_id, 'number');
  assert.ok(members.every((m) => !('member_key' in m) && !('joined_at' in m) && !('protocol' in m)));

  // A rejoin of the same player replaces its old connection
  const again = (await legacy(room, 1)).peer;
  await a.next('replaced');
  assert.deepEqual(ids((await again.next('members', (m) => m.members.length === 2)).members), [1, 2]);
  await Promise.all([a, b, again].map(close));
});

test('protocol 1: old versions and bad keys are refused', async () => {
  assert.equal((await legacy(newRoom(), 1, { version: '1.4.9.81' })).status, 426);
  assert.equal((await legacy(newRoom(), 1, { version: '' })).status, 426);
  assert.equal((await legacy('short', 1)).status, 400);
  // A protocol this relay does not know
  assert.equal((await upgrade(newRoom(), '1', credential('a'), { protocol: '3' })).status, 426);
});

// ─── Protocol 2 (Rose 1.5.7's relay tests, Parasite names) ──────────────────

test('protocol 2: incomplete upgrades do not receive a socket', async () => {
  const room = newRoom();
  const missing = await upgrade(room, '1', undefined);
  assert.equal(missing.status, 400);
  assert.equal(missing.peer, null);
  assert.equal((await upgrade(room, '18446744073709551616', credential('a'))).status, 400);
  assert.equal((await upgrade(room, '1', credential('a'), { path: '/other' })).status, 426);
  assert.equal((await upgrade('not-hex-room-key-0000000000000000', '1', credential('a'))).status, 400);
  assert.equal((await upgrade(room, '1', credential('a'), { version: '1.4.9.81' })).status, 426);
});

test('protocol 2: an invite cannot replace a connected member, whose identity stays fixed', async () => {
  const room = newRoom();
  const id = '18446744073709551615';
  const owner = connect(await upgrade(room, id, credential('a')));
  const initial = (await owner.next('members')).members;
  assert.equal(initial.length, 1);
  assert.equal(initial[0].summoner_id, id);
  assert.equal(initial[0].summoner_name, 'Lótus 🌹');
  assert.match(initial[0].member_key, /^[0-9a-f]{64}$/);
  assert.notEqual(initial[0].member_key, credential('a'));
  assert.ok(!('joined_at' in initial[0]) && !('protocol' in initial[0]));

  const refused = await upgrade(room, id, credential('b'));
  assert.equal(refused.status, 403);
  assert.equal(refused.peer, null);
  const peer = connect(await upgrade(room, '2', credential('b'), { name: 'Peer' }));
  assert.equal((await owner.next('members')).members.length, 2);

  peer.socket.send(JSON.stringify({ type: 'join', summoner_id: id, summoner_name: 'Other' }));
  peer.socket.send('null');
  peer.socket.send(JSON.stringify({ type: 'skin', summoner_id: id, skin: { skin_id: 23 } }));
  const { members } = await owner.next('members', (m) => m.members.some((x) => x.skin));
  assert.deepEqual(members.find((member) => member.summoner_id === id), initial[0]);
  assert.deepEqual(members.find((member) => member.summoner_id === '2')?.skin, { skin_id: 23 });

  const reconnected = connect(await upgrade(room, id, credential('a')));
  await owner.next('replaced');
  assert.equal((await reconnected.next('members')).members.length, 2);
  await Promise.all([owner, peer, reconnected].map(close));

  // Once the member has left, another installation (a reinstall, another PC) takes the ID
  const reinstalled = connect(await upgrade(room, id, credential('c')));
  const [rejoined] = (await reinstalled.next('members', (m) => m.members.length === 1)).members;
  assert.equal(rejoined.summoner_id, id);
  assert.notEqual(rejoined.member_key, initial[0].member_key);
  await close(reinstalled);
});

test('protocol 2: the same credential gives the same member_key in every room', async () => {
  const first = connect(await upgrade(newRoom(), '9', credential('a')));
  const same = connect(await upgrade(newRoom(), '9', credential('a')));
  const different = connect(await upgrade(newRoom(), '9', credential('b')));
  const [knownKey, sameKey, differentKey] = await Promise.all(
    [first, same, different].map(async (peer) => (await peer.next('members')).members[0].member_key),
  );
  assert.equal(knownKey, sameKey);
  assert.notEqual(knownKey, differentKey);
  await Promise.all([first, same, different].map(close));
});

test('protocol 2: concurrent joins admit one installation, and none is bound after it leaves', async () => {
  const room = newRoom();
  const secrets = [credential('a'), credential('b')];
  const responses = await Promise.all(secrets.map((secret) => upgrade(room, '1', secret)));
  assert.deepEqual(responses.map((response) => response.status).sort(), [101, 403]);
  const winner = responses.findIndex((response) => response.status === 101);
  const first = connect(responses[winner]);
  await first.next('members');
  await close(first);

  await worker.dispose();
  worker = startWorker();
  const other = connect(await upgrade(room, '1', secrets[1 - winner]));
  assert.equal((await other.next('members')).members[0].summoner_id, '1');
  await close(other);
});

test('protocol 2: X-Lust-* and X-Rose-* headers work too, answered under the same name', async () => {
  const room = newRoom();
  const lust = await upgrade(room, '5', credential('a'), { prefix: 'X-Lust-' });
  const peer = connect(lust, 'x-lust-party-protocol');
  assert.equal(lust.headers['x-parasite-party-protocol'], undefined);
  connect(await upgrade(newRoom(), '6', credential('a'), { prefix: 'X-Rose-' }), 'x-rose-party-protocol').socket.close();
  await close(peer);
});

test('protocol 2: a room holds ten connections', async () => {
  const room = newRoom();
  const peers = [];
  for (let i = 1; i <= 10; i++) peers.push(connect(await upgrade(room, String(i), credential('a'))));
  assert.equal((await upgrade(room, '11', credential('a'))).status, 409);
  assert.equal((await legacy(room, 11)).status, 409);
  await Promise.all(peers.map(close));
});

// ─── Mixed rooms ─────────────────────────────────────────────────────────────

test('mixed: protocol 1 sees everyone, protocol 2 sees protocol 2 members only', async () => {
  const room = newRoom();
  const big = '18446744073709551615'; // past 2^53: must reach protocol 1 exactly
  const old = (await legacy(room, 1)).peer;
  await old.next('members');
  old.socket.send(JSON.stringify({ type: 'skin', skin: { skin_id: 1001 } }));

  const fresh = connect(await upgrade(room, big, credential('a')));
  const seen = (await fresh.next('members')).members;
  assert.deepEqual(ids(seen), [big]);
  fresh.socket.send(JSON.stringify({ type: 'skin', skin: { skin_id: 2002, removed: ['7'] } }));

  const update = await old.next('members', (m) => m.members.length === 2 && m.members.some((x) => x.skin?.skin_id === 2002));
  assert.match(update.raw, /"summoner_id":18446744073709551615,/); // a JSON number, not a string
  const mine = update.members.find((m) => m.summoner_id === 1);
  const theirs = update.members.find((m) => m.summoner_id !== 1);
  assert.deepEqual(mine.skin, { skin_id: 1001 });
  assert.equal(typeof theirs.summoner_id, 'number');
  assert.equal(theirs.summoner_name, 'Lótus 🌹');
  assert.deepEqual(theirs.skin, { skin_id: 2002, removed: ['7'] });

  // The protocol 2 member never sees the protocol 1 one, whatever it sends
  old.socket.send(JSON.stringify({ type: 'skin', skin: { skin_id: 1003 } }));
  await old.next('members', (m) => m.members.some((x) => x.skin?.skin_id === 1003));
  const latest = (await fresh.next('members')).members;
  assert.deepEqual(ids(latest), [big]);
  assert.ok(latest.every((m) => /^[0-9a-f]{64}$/.test(m.member_key)));
  await Promise.all([old, fresh].map(close));
});

test('mixed: a protocol 1 join cannot take a protocol 2 member\'s ID', async () => {
  const room = newRoom();
  const member = connect(await upgrade(room, '42', credential('a')));
  await member.next('members');
  const impostor = (await legacy(room, 42, { name: 'Impostor' })).peer;
  const other = (await legacy(room, 43)).peer;
  // The impostor stays unlisted; the honest protocol 1 player is listed
  const { members } = await other.next('members', (m) => m.members.some((x) => x.summoner_id === 43));
  assert.deepEqual(ids(members), [42, 43]);
  assert.equal(members.find((m) => m.summoner_id === 42).summoner_name, 'Lótus 🌹');
  assert.equal(member.socket.readyState, WebSocket.OPEN);
  await Promise.all([member, impostor, other].map(close));
});

test('mixed: a player who updates (protocol 1 then 2) replaces its old connection', async () => {
  const room = newRoom();
  const before = (await legacy(room, 77)).peer;
  const watcher = (await legacy(room, 78)).peer;
  await watcher.next('members', (m) => m.members.length === 2);
  const after = connect(await upgrade(room, '77', credential('a')));
  await before.next('replaced');
  assert.deepEqual(ids((await after.next('members')).members), ['77']);
  const { members } = await watcher.next('members', (m) => m.members.some((x) => x.summoner_id === 77 && x.summoner_name === 'Lótus 🌹'));
  assert.deepEqual(ids(members), [77, 78]);
  await Promise.all([before, watcher, after].map(close));
});

// ─── The rest of the Worker ──────────────────────────────────────────────────

test('health check and friends directory still answer', async () => {
  const base = await worker.ready;
  const health = await (await worker.dispatchFetch(new URL('/', base))).json();
  assert.deepEqual(health, { status: 'ok', service: 'parasite-party-relay', protocols: [1, 2] });
  const a = 'a'.repeat(32);
  const b = 'b'.repeat(32);
  const ask = (me, friends) => worker.dispatchFetch(new URL('/friends?v=2.11', base), {
    method: 'POST', body: JSON.stringify({ me, friends }), headers: { 'Content-Type': 'application/json' },
  });
  await ask(a, [b]);
  assert.deepEqual(await (await ask(b, [a])).json(), { matches: [a] });
  assert.equal((await worker.dispatchFetch(new URL('/friends?v=1.0', base), { method: 'POST', body: '{}' })).status, 426);
});
