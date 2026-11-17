import { DurableObject } from 'cloudflare:workers';

/**
 * Parasite Party Room - Durable Object (from Rose's relay, Rose 1.5.7's protocol 2)
 *
 * Shared room where party members broadcast their skin selections, at most ten
 * connections at a time. One room serves two protocols, chosen per connection:
 *
 * - Protocol 2 (Parasite 2.11+, `p=2` on the URL): the player comes in the upgrade's
 *   headers (X-Parasite-Summoner-Id, X-Parasite-Summoner-Name, Authorization: Bearer
 *   <64 hex>), the answer carries X-Parasite-Party-Protocol: 2, and each member is listed
 *   with its summoner_id as a decimal string and a member_key (SHA-256 of its credential).
 *   A connected member can only be replaced by the installation it joined from.
 * - Protocol 1 (Parasite <= 2.10, Lust): no `p`, the player announces itself with a
 *   `join` message, IDs are JSON numbers, there is no member_key.
 *
 * Mixed rooms:
 * - Protocol 2 connections see only protocol 2 members. Protocol 2 clients drop members
 *   without a member_key anyway, and a protocol 1 player could claim any ID.
 * - Protocol 1 connections see everyone: their own members as before, and protocol 2
 *   members with a numeric summoner_id (written as is, so 64-bit IDs stay exact).
 * - A protocol 1 `join` with the ID of a connected protocol 2 member is ignored (that
 *   connection stays in the room, unlisted). A protocol 2 connection with the ID of a
 *   protocol 1 member replaces it (the same player, updated).
 * - Every connection counts toward the ten.
 */

interface Member {
  protocol: 2;
  summoner_id: string;
  summoner_name: string;
  member_key: string;
  skin?: Record<string, unknown> | null;
  joined_at: number;
}

interface LegacyMember {
  protocol?: 1;
  // Whatever the client sent: a number from Parasite and Lust. Unset until its `join`
  summoner_id?: number;
  summoner_name?: string;
  skin?: unknown;
  joined_at?: number;
}

type Info = Member | LegacyMember;
// What a connection carries: its member, or that it was dropped
type Attachment = Info | { dropped: true } | null;

interface Identity {
  id: string;
  name: string;
  credential: string;
  // The header prefix the client used, for the protocol header of the answer
  prefix: string;
}

// Parasite 2.11 sends X-Parasite-* (party/network/ws_relay.py). Lust shares this relay:
// a Lust moved to protocol 2 would send X-Lust-*, and Rose sends X-Rose-*
export const HEADER_PREFIXES = ['X-Parasite-', 'X-Lust-', 'X-Rose-'];

/** The player of a protocol 2 upgrade, or null when its headers are missing or invalid. */
export function readIdentity(headers: Headers): Identity | null {
  const prefix = HEADER_PREFIXES.find((p) => headers.has(p + 'Summoner-Id'));
  if (!prefix) return null;
  const id = headers.get(prefix + 'Summoner-Id');
  const authorization = headers.get('Authorization') ?? '';
  const encodedName = headers.get(prefix + 'Summoner-Name') ?? '';
  const credential = /^Bearer ([0-9a-f]{64})$/.exec(authorization)?.[1];
  if (!credential || !id || !/^[1-9][0-9]{0,19}$/.test(id)
      || BigInt(id) > 0xffffffffffffffffn || encodedName.length > 1024) return null;
  try {
    const name = decodeURIComponent(encodedName);
    if (name.length > 128 || /[\u0000-\u001f\u007f]/.test(name)) return null;
    return { id, name: name || 'Unknown', credential, prefix };
  } catch {
    return null;
  }
}

const isMember = (info: Info): info is Member => info.protocol === 2;

export class PartyRoom extends DurableObject {
  private static MAX_MEMBERS = 10;
  private static MAX_MESSAGE_BYTES = 8 * 1024;
  // Clients ping every 25s; a socket silent for longer is gone (PC asleep,
  // network lost...) even though no close frame arrived
  private static STALE_MS = 90_000;
  // Rose before 1.4.0 never pings: timing its sockets out after 90s made those
  // clients reconnect, and wake the room, all day. Theirs only go after this
  private static NEVER_PINGED_STALE_MS = 30 * 60_000;

  constructor(ctx: DurableObjectState, env: any) {
    super(ctx, env);
    this.ctx.setWebSocketAutoResponse(
      new WebSocketRequestResponsePair('ping', 'pong'),
    );
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    return url.searchParams.get('p') === '2' ? this.acceptMember(request) : this.acceptLegacy(url);
  }

  // Protocol 2: the player is known (and checked) before the socket opens
  private async acceptMember(request: Request): Promise<Response> {
    const identity = readIdentity(request.headers);
    if (!identity) return new Response('Invalid party identity', { status: 400 });

    const proof = new TextEncoder().encode('parasite-party-member-v2:' + identity.id + ':' + identity.credential);
    const digest = await crypto.subtle.digest('SHA-256', proof);
    const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
    // Keep the check and the accept synchronous after hashing, so a concurrent
    // upgrade sees the socket this one opens
    const active = this.openSockets();
    const same = active.filter(({ info }) => info.summoner_id !== undefined && String(info.summoner_id) === identity.id);
    // A connected member can only be replaced by the installation it joined
    // from. Once that socket is gone, any installation can take the ID again,
    // so a reinstall or another PC is never locked out of a room
    if (same.some(({ info }) => isMember(info) && info.member_key !== hash)) {
      return new Response('Party identity is connected from another installation', { status: 403 });
    }
    if (active.length - same.length >= PartyRoom.MAX_MEMBERS) {
      this.log('full', { open: active.length });
      return new Response('Room is full', { status: 409 });
    }

    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server);
    server.serializeAttachment({
      protocol: 2,
      summoner_id: identity.id,
      summoner_name: identity.name,
      member_key: hash,
      joined_at: Date.now(),
    } satisfies Member);
    // Our own earlier connection, or this player's protocol 1 one (it updated)
    for (const { socket } of same) {
      this.notifyReplaced(socket);
      this.dropSocket(socket, 'replaced');
    }
    this.log('join', { p: 2, summoner_id: identity.id, replaced: same.length, v: new URL(request.url).searchParams.get('v') });
    this.broadcastMembers();
    return new Response(null, {
      status: 101,
      headers: { [identity.prefix + 'Party-Protocol']: '2' },
      webSocket: client,
    });
  }

  // Protocol 1: the player announces itself with a `join` message once connected
  private acceptLegacy(url: URL): Response {
    const active = this.openSockets();
    if (active.length >= PartyRoom.MAX_MEMBERS) {
      this.log('full', { open: active.length });
      return new Response('Room is full', { status: 409 });
    }

    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server);
    server.serializeAttachment({ protocol: 1, joined_at: Date.now() } satisfies LegacyMember);
    this.log('connect', { p: 1, open: active.length + 1, v: url.searchParams.get('v') });

    // Send current member list to the new joiner
    server.send(this.legacyPayload(this.openSockets()));
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    const info = this.info(ws);
    if (!info || typeof message !== 'string' || message === 'pong') return;
    if (isMember(info)) this.memberMessage(ws, info, message);
    else this.legacyMessage(ws, info, message);
  }

  private memberMessage(ws: WebSocket, member: Member, message: string) {
    if (message.length > PartyRoom.MAX_MESSAGE_BYTES
        || new TextEncoder().encode(message).byteLength > PartyRoom.MAX_MESSAGE_BYTES) return;
    let msg: { type?: unknown; skin?: unknown } | null;
    try {
      msg = JSON.parse(message);
    } catch {
      return;
    }
    if (!msg || typeof msg !== 'object') return;
    switch (msg.type) {
      // The identity comes from the upgrade: `join` and IDs in messages are ignored
      case 'skin': {
        const skin = msg.skin;
        if (skin !== null && (!skin || typeof skin !== 'object' || Array.isArray(skin))) return;
        member.skin = skin as Member['skin'];
        try {
          ws.serializeAttachment(member);
        } catch {
          return; // The parsed object can exceed the attachment's storage limit
        }
        this.broadcastMembers();
        break;
      }
      case 'leave': {
        this.dropSocket(ws, 'left');
        ws.close(1000, 'client left');
        this.broadcastMembers();
        break;
      }
    }
  }

  private legacyMessage(ws: WebSocket, existing: LegacyMember, message: string) {
    let msg: any;
    try {
      msg = JSON.parse(message);
    } catch {
      return;
    }
    if (!msg || typeof msg !== 'object') return;

    switch (msg.type) {
      case 'join': {
        // A protocol 2 member's place is its own: a claim without its credential is ignored
        const claimed = String(msg.summoner_id);
        const taken = this.openSockets().some(({ socket, info }) =>
          socket !== ws && isMember(info) && info.summoner_id === claimed);
        if (taken) {
          this.log('join_ignored', { p: 1, summoner_id: msg.summoner_id });
          break;
        }
        // Member announces themselves
        const info: LegacyMember = {
          protocol: 1,
          summoner_id: msg.summoner_id,
          summoner_name: String(msg.summoner_name || 'Unknown').slice(0, 64),
          joined_at: Date.now(),
        };
        ws.serializeAttachment(info);
        // A rejoin replaces the member's previous connection, which dropped
        // without a close frame
        let replaced = 0;
        for (const { socket, info: other } of this.openSockets()) {
          if (socket === ws || isMember(other)) continue;
          if (other.summoner_id !== undefined && other.summoner_id === info.summoner_id) {
            this.notifyReplaced(socket);
            this.dropSocket(socket, 'replaced');
            replaced++;
          }
        }
        this.log('join', { p: 1, summoner_id: info.summoner_id, replaced });
        this.broadcastMembers();
        break;
      }
      case 'skin': {
        // Member updated their skin selection
        if (existing.summoner_id !== undefined) {
          // A pick is a few small fields: anything bigger is not a Parasite client's
          const skin = msg.skin && typeof msg.skin === 'object' ? msg.skin : null;
          existing.skin = skin && JSON.stringify(skin).length <= 1024 ? skin : null;
          ws.serializeAttachment(existing);
          this.broadcastMembers();
        }
        break;
      }
      case 'leave': {
        ws.close(1000, 'client left');
        break;
      }
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string, wasClean: boolean) {
    const info = this.info(ws);
    this.log('client_close', { summoner_id: info?.summoner_id, code, reason, wasClean });
    // Answer the close frame so the client isn't left waiting. A connection
    // lost without one (1006) has no one left to answer (see dropSocket)
    if (wasClean) {
      try {
        ws.close(1000, 'closed');
      } catch {}
    }
    this.broadcastMembers();
  }

  async webSocketError(ws: WebSocket, error: unknown) {
    const info = this.info(ws);
    this.log('error', { summoner_id: info?.summoner_id, error: String(error) });
    this.dropSocket(ws, 'error');
    this.broadcastMembers();
  }

  // A connection whose other end is gone (it stopped pinging, or its player
  // joined again) is left out of the room rather than closed: closing it waits
  // on a client that never answers, which kept rooms awake, and billed, for up
  // to 15 minutes each time. Cloudflare cuts it once nothing goes through it
  // for 100s
  private dropSocket(ws: WebSocket, reason: string) {
    this.log('drop', { summoner_id: this.info(ws)?.summoner_id, reason });
    try {
      ws.serializeAttachment({ dropped: true });
    } catch {}
  }

  private notifyReplaced(ws: WebSocket) {
    try {
      ws.send(JSON.stringify({ type: 'replaced' }));
    } catch {}
  }

  // The connection's member (protocol 1 before its join too), null once dropped.
  // A connection from before this code (no attachment yet) is a protocol 1 one
  private info(ws: WebSocket): Info | null {
    let attachment: Attachment;
    try {
      attachment = ws.deserializeAttachment() as Attachment;
    } catch {
      return null;
    }
    if (attachment && 'dropped' in attachment) return null;
    return attachment ?? {};
  }

  // Open sockets, dropping the ones that stopped pinging
  private openSockets(): { socket: WebSocket; info: Info }[] {
    const now = Date.now();
    const open: { socket: WebSocket; info: Info }[] = [];
    for (const socket of this.ctx.getWebSockets()) {
      if (socket.readyState !== WebSocket.READY_STATE_OPEN) continue;
      const info = this.info(socket);
      if (!info) continue;
      const lastPing = this.ctx.getWebSocketAutoResponseTimestamp(socket)?.getTime();
      const lastSeen = lastPing ?? info.joined_at ?? now;
      const staleMs = lastPing === undefined && !isMember(info) ? PartyRoom.NEVER_PINGED_STALE_MS : PartyRoom.STALE_MS;
      if (now - lastSeen > staleMs) {
        this.dropSocket(socket, 'stale');
        continue;
      }
      open.push({ socket, info });
    }
    return open;
  }

  // One line per connection event in Workers Logs, to see why rooms churn.
  // room matches the objectId of the Durable Objects analytics
  private log(event: string, fields: Record<string, unknown>) {
    console.log(JSON.stringify({ event, room: this.ctx.id.toString().slice(0, 12), ...fields }));
  }

  // What protocol 2 connections see: protocol 2 members only
  private memberPayload(open: { info: Info }[]): string {
    const members = open
      .map(({ info }) => info)
      .filter(isMember)
      .map(({ protocol, joined_at, ...member }) => member);
    return JSON.stringify({ type: 'members', members });
  }

  // What protocol 1 connections see: everyone joined, IDs as JSON numbers
  private legacyPayload(open: { info: Info }[]): string {
    const members: string[] = [];
    for (const { info } of open) {
      if (isMember(info)) {
        // The decimal string written as a number: exact even past 2^53
        let text = `{"summoner_id":${info.summoner_id},"summoner_name":${JSON.stringify(info.summoner_name)}`;
        if (info.skin !== undefined) text += `,"skin":${JSON.stringify(info.skin)}`;
        members.push(text + '}');
      } else if (info.summoner_id) {
        const { protocol, joined_at, ...member } = info;
        members.push(JSON.stringify(member));
      }
    }
    return `{"type":"members","members":[${members.join(',')}]}`;
  }

  private broadcastMembers() {
    const open = this.openSockets();
    let member: string | undefined;
    let legacy: string | undefined;
    for (const { socket, info } of open) {
      try {
        socket.send(isMember(info)
          ? (member ??= this.memberPayload(open))
          : (legacy ??= this.legacyPayload(open)));
      } catch {}
    }
  }
}
