import { readIdentity } from './room';
export { PartyRoom } from './room';
export { FriendsDirectory } from './directory';

interface Env {
  ROOM: DurableObjectNamespace;
  DIRECTORY: DurableObjectNamespace;
}

// Parasite's relay (parasite/relay, deployed by .github/workflows/relay-deploy.yml, see README.md).
// Parasite shares skins on its own from 1.4.9.82 (launcher/parasite_share.py); a client
// that sends no version, or an older one, is refused before waking a room.
// Lust (1.4.9.x) and Parasite up to 2.10 speak protocol 1; Parasite 2.11+ (Rose 1.5.7's
// party code) sends p=2 and its identity in headers (see room.ts). Both meet in one room
const MIN_VERSION = [1, 4, 9, 82];

function supported(version: string | null): boolean {
  if (!version) return false;
  const parts = version.split('.').map((part) => parseInt(part, 10));
  for (let i = 0; i < MIN_VERSION.length; i++) {
    const part = Number.isFinite(parts[i]) ? parts[i] : 0;
    if (part !== MIN_VERSION[i]) return part > MIN_VERSION[i];
  }
  return true;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Health check
    if (url.pathname === '/' && request.method === 'GET') {
      return new Response(JSON.stringify({ status: 'ok', service: 'parasite-party-relay', protocols: [1, 2] }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Which League friends use Parasite: POST /friends?v=<version> {me, friends} (see directory.ts)
    if (url.pathname === '/friends' && request.method === 'POST') {
      if (!supported(url.searchParams.get('v'))) {
        return new Response('Update Parasite to share skins', { status: 426 });
      }
      if (Number(request.headers.get('Content-Length') || 0) > 64_000) {
        return new Response('Too large', { status: 413 });
      }
      const stub = env.DIRECTORY.get(env.DIRECTORY.idFromName('lol-friends'));
      return stub.fetch(request);
    }

    // WebSocket upgrade at /room?key=<room_id>
    const upgrade = request.headers.get('Upgrade');
    if (upgrade?.toLowerCase() === 'websocket') {
      const roomKey = url.searchParams.get('key');
      const protocol = url.searchParams.get('p');
      if (protocol === '2') {
        // Rose 1.5.7's checks: /room only, 32 hex room keys, identity headers
        if (url.pathname !== '/room') {
          return new Response('Parasite Party Relay - WebSocket upgrade required', { status: 426 });
        }
        if (!roomKey || !/^[0-9a-f]{32}$/.test(roomKey)) {
          return new Response('Invalid room key', { status: 400 });
        }
        if (!supported(url.searchParams.get('v'))) {
          return new Response('Update Parasite to share skins', { status: 426 });
        }
        if (!readIdentity(request.headers)) {
          return new Response('Invalid party identity', { status: 400 });
        }
      } else {
        // Protocol 1 sends no p. A protocol this relay doesn't know is a newer client's
        if (protocol !== null && protocol !== '1') {
          return new Response('Unsupported party protocol', { status: 426 });
        }
        if (!roomKey || roomKey.length < 8 || roomKey.length > 64) {
          return new Response('Invalid room key', { status: 400 });
        }
        if (!supported(url.searchParams.get('v'))) {
          return new Response('Update Parasite to share skins', { status: 426 });
        }
      }

      // One room for both protocols, named by its key as before (rooms survive this deploy)
      const id = env.ROOM.idFromName(roomKey);
      const stub = env.ROOM.get(id);
      return stub.fetch(request);
    }

    return new Response('Parasite Party Relay - WebSocket upgrade required', { status: 426 });
  },
};
