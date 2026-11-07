"""Auto Accept, Auto Ban, Auto Pick, Auto Requeue and dodging from the desktop app.

While League is open a small thread watches the client (LCU): it accepts the ready check,
in champ select it bans and picks for the player when their turn comes, taking the first
champion of their list that is still free, and after a matchmade game it goes back to the
lobby and starts the queue again. Each switch and both lists are the player's own, kept in
Parasite's data folder as parasite-auto.json.

Bans and picks can wait for the last seconds of the turn (ban_at / pick_at seconds left; the
champion is hovered right away so teammates see it). The queue can start again a while after
the game (requeue_delay), after a champ select someone dodged (requeue_dodge), and searching
starts over once it runs well past the estimated time (requeue_refresh). A dodge can be armed
for the last second of champ select.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

from utils.core.logging import get_logger

log = get_logger()

FILE = "parasite-auto.json"
MAX_CHOICES = 5
SWITCHES = ("accept", "ban", "pick", "requeue", "requeue_dodge", "requeue_refresh")
# Seconds left in the turn when the ban or pick locks in (0: right away)
AT_CHOICES = (0, 1, 3, 5, 10)
DELAY_CHOICES = (0, 10, 30, 60, 120)
DEFAULTS = {"accept": False, "ban": False, "pick": False, "requeue": False, "requeue_dodge": False,
            "requeue_refresh": False, "ban_at": 0, "pick_at": 0, "requeue_delay": 0, "bans": [], "picks": []}
LAST_SECOND_MS = 1200   # "the last second": what is left when the lock-in is sent
DODGE_AT_MS = 1500      # the armed dodge goes this long before champ select ends
FAST_S = 0.25           # polling near a deadline
DODGE_REQUEUE_S = 15 * 60  # a dodge penalty can keep the queue closed this long
REFRESH_OVER_S = 60.0   # a search this far past its estimate starts over
REFRESH_EVERY_S = 300.0
IDLE_S = 3.0   # League closed or nothing to do
BUSY_S = 1.0   # ready check or champ select
CREDS_TTL_S = 30.0
MAX_TRIES = 30  # about one a second: the client can ignore a lock-in for the first seconds of a turn
REQUEUE_WAIT_S = 90.0  # after "play again", how long the lobby may take before the queue starts
END_PHASES = ("PreEndOfGame", "WaitingForStats", "EndOfGame")

_lock = threading.Lock()
_cache: Optional[dict] = None
_thread: Optional[threading.Thread] = None
_creds: dict = {"at": 0.0, "value": None}
_done: dict = {}  # action id -> tries in this champ select
_hovered: dict = {}  # action id -> champion hovered while waiting for the last seconds
_requeue: dict = {"game": None, "until": 0.0, "not_before": 0.0}  # the game already requeued; queue again until this time
_refresh: dict = {"at": 0.0}


# ---- settings ----

def clean(data) -> dict:
    out = dict(DEFAULTS)
    if not isinstance(data, dict):
        return out
    for key in SWITCHES:
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    for key, choices in (("ban_at", AT_CHOICES), ("pick_at", AT_CHOICES), ("requeue_delay", DELAY_CHOICES)):
        if data.get(key) in choices and not isinstance(data.get(key), bool):
            out[key] = data[key]
    for key in ("bans", "picks"):
        values = data.get(key) if isinstance(data.get(key), list) else []
        ids = []
        for value in values:
            if isinstance(value, int) and not isinstance(value, bool) and value > 0 and value not in ids:
                ids.append(value)
        out[key] = ids[:MAX_CHOICES]
    return out


def _path() -> Path:
    from utils.core.paths import get_user_data_dir
    return get_user_data_dir() / FILE


def settings() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            try:
                _cache = clean(json.loads(_path().read_text(encoding="utf-8")))
            except (OSError, ValueError):
                _cache = dict(DEFAULTS)
        return json.loads(json.dumps(_cache))


def update(changes: dict) -> str:
    global _cache
    merged = settings()
    merged.update(changes if isinstance(changes, dict) else {})
    cleaned = clean(merged)
    with _lock:
        _cache = cleaned
        try:
            _path().write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning(f"[Auto] Could not save: {exc}")
            return "Kaydedilemedi"
    if _any_on(cleaned):
        start()
    return ""


def _reveal() -> dict:
    """Lobby Reveal: its switch and the teammates it found in this champ select."""
    from launcher.parasite_settings import enabled
    out = {"on": enabled("lobby_reveal"), "active": False, "players": [], "multiUrl": ""}
    try:
        from threads.core.lobby_reveal_thread import latest
        team = latest()
    except Exception:  # noqa: BLE001
        team = {}
    if team.get("active"):
        out.update(active=True, multiUrl=team.get("multiUrl", ""),
                   players=[{k: p.get(k, "") for k in ("gameName", "gameTag", "position", "opggUrl")}
                            for p in team.get("players") or []])
    return out


def listing() -> dict:
    from launcher import parasite_counters, parasite_skins
    return dict(settings(), champions=[{"id": c["id"], "name": c["name"]} for c in parasite_skins.champions()],
                max=MAX_CHOICES, reveal=_reveal(), counters=parasite_counters.board(),
                dodge={"armed": _dodge["armed"], "state": _dodge["state"]}, atChoices=AT_CHOICES,
                delayChoices=DELAY_CHOICES)


def dumps_listing() -> bytes:
    return json.dumps(listing(), ensure_ascii=False).encode("utf-8")


# ---- champ select ----

def _taken(session: dict) -> set:
    """Champions nobody else may pick now: banned, picked, or hovered by a teammate."""
    taken = set()
    bans = session.get("bans") or {}
    for key in ("myTeamBans", "theirTeamBans"):
        taken.update(c for c in bans.get(key) or [] if isinstance(c, int) and c > 0)
    for group in session.get("actions") or []:
        for action in group or []:
            if action.get("completed") and action.get("championId"):
                taken.add(action["championId"])
    return taken


def choose(session: dict, config: dict, pickable=None, bannable=None) -> Optional[tuple]:
    """(action id, champion id, kind) to answer now, or None. Only the player's own action
    that is in progress; bans skip what a teammate wants to play."""
    if not isinstance(session, dict):
        return None
    me = session.get("localPlayerCellId")
    taken = _taken(session)
    groups = [g for g in session.get("actions") or [] if isinstance(g, list)]
    # The current turn: actions marked in progress; when the client leaves that flag out,
    # the first group that still has an open action
    current = next((g for g in groups if any(not a.get("completed") for a in g)), [])
    friends = {m.get("championPickIntent") for m in session.get("myTeam") or [] if m.get("cellId") != me}
    friends.update(m.get("championId") for m in session.get("myTeam") or [] if m.get("cellId") != me)
    for group in groups:
        for action in group:
            in_progress = action.get("isInProgress")
            if in_progress is None:
                in_progress = group is current
            if action.get("actorCellId") != me or action.get("completed") or not in_progress:
                continue
            kind = action.get("type")
            if kind == "ban" and config.get("ban"):
                allowed = bannable
                choices = [c for c in config.get("bans") or [] if c not in taken and c not in friends]
            elif kind == "pick" and config.get("pick"):
                allowed = pickable
                choices = [c for c in config.get("picks") or [] if c not in taken]
            else:
                continue
            # The client's own list of what may be banned or picked now; when it leaves out
            # every choice the list itself may be wrong, so try the choice and let the client say no
            if allowed is not None and any(c in allowed for c in choices):
                choices = [c for c in choices if c in allowed]
            if choices:
                return action.get("id"), choices[0], kind
    return None


# ---- the client ----

def _credentials():
    now = time.monotonic()
    if _creds["value"] and now - _creds["at"] < CREDS_TTL_S:
        return _creds["value"]
    from launcher.parasite_offline import _lcu_credentials
    _creds.update(at=now, value=_lcu_credentials())
    return _creds["value"]


def _lcu(method: str, path: str, body=None):
    creds = _credentials()
    if not creds:
        _note("creds", "[Auto] League client not found (no LeagueClientUx port/token)")
        return None
    port, token = creds
    import requests
    try:
        response = requests.request(method, f"https://127.0.0.1:{port}{path}", auth=("riot", token), json=body,
                                    verify=False, timeout=3, proxies={"http": None, "https": None})
    except requests.RequestException:
        _creds["at"] = 0.0  # League may have restarted with a new port
        return None
    if not response.ok:
        if method != "GET":
            log.warning(f"[Auto] {method} {path} -> HTTP {response.status_code}: {response.text[:200]}")
        return None
    try:
        return response.json() if response.content else {}
    except ValueError:
        return {}


def _accept() -> None:
    check = _lcu("GET", "/lol-matchmaking/v1/ready-check")
    if isinstance(check, dict) and check.get("state") == "InProgress" and check.get("playerResponse") == "None":
        if _lcu("POST", "/lol-matchmaking/v1/ready-check/accept") is not None:
            log.info("[Auto] Ready check accepted")


def _wait_ms(config: dict, kind: str, timer: dict) -> float:
    """How long the ban or pick should still wait: until ban_at / pick_at seconds are left in the
    turn (never later than the last second). 0 when it goes now."""
    seconds = config.get(f"{kind}_at") or 0
    left = timer.get("adjustedTimeLeftInPhase")
    if not seconds or timer.get("phase") != "BAN_PICK" or not isinstance(left, (int, float)):
        return 0.0
    return max(0.0, left - max(seconds * 1000.0, LAST_SECOND_MS))


def _champ_select(config: dict) -> float:
    """Ban or pick for the player when their turn comes; returns how soon to look again."""
    session = _lcu("GET", "/lol-champ-select/v1/session")
    if not isinstance(session, dict):
        return BUSY_S
    _dodge_check(session)
    if not (config["ban"] or config["pick"]):
        return FAST_S if _dodge["armed"] else BUSY_S
    pickable = _lcu("GET", "/lol-champ-select/v1/pickable-champion-ids") if config["pick"] else None
    bannable = _lcu("GET", "/lol-champ-select/v1/bannable-champion-ids") if config["ban"] else None
    found = choose(session, config, set(pickable) if isinstance(pickable, list) and pickable else None,
                   set(bannable) if isinstance(bannable, list) and bannable else None)
    if not found:
        mine = [a for g in session.get("actions") or [] for a in g or []
                if a.get("actorCellId") == session.get("localPlayerCellId") and not a.get("completed")]
        me = session.get("localPlayerCellId")
        friends = sorted({m.get("championPickIntent") or m.get("championId") or 0
                          for m in session.get("myTeam") or [] if m.get("cellId") != me} - {0})
        _note(f"none-{[(a.get('id'), a.get('type'), a.get('isInProgress')) for a in mine]}",
              f"[Auto] Nothing to do: my open actions {[(a.get('type'), a.get('isInProgress')) for a in mine]}, "
              f"ban {'on' if config['ban'] else 'off'} {config['bans']}, "
              f"pick {'on' if config['pick'] else 'off'} {config['picks']}, "
              f"taken {sorted(_taken(session))}, teammates want {friends}, "
              f"timer {(session.get('timer') or {}).get('phase')}")
        return BUSY_S
    action_id, champion, kind = found
    timer = session.get("timer") or {}
    wait_ms = _wait_ms(config, kind, timer)
    if wait_ms > 0:
        # Hover now so teammates see it; lock in during the last seconds of the turn
        if _hovered.get(action_id) != champion:
            if _lcu("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}", {"championId": champion}) is not None:
                _hovered[action_id] = champion
                log.info(f"[Auto] {kind} {champion} hovered; locking in with {config[kind + '_at']}s left")
        return FAST_S if wait_ms < 3000 else BUSY_S
    # Ranked opens with a planning phase where the ban already shows as in progress but the
    # client won't take it yet: wait for the ban phase instead of using up the tries
    if (session.get("timer") or {}).get("phase") == "PLANNING":
        _note("planning", "[Auto] Planning phase: waiting for the ban phase")
        return BUSY_S
    # The client may answer OK and still leave the action open (seen with bans), so an
    # action counts as done only once the session shows it completed: try again until then
    tries = _done.get(action_id, 0)
    if tries >= MAX_TRIES:
        _note(f"gave-up-{action_id}", f"[Auto] Gave up on {kind} {champion} (action {action_id})")
        return BUSY_S
    _done[action_id] = tries + 1
    path = f"/lol-champ-select/v1/session/actions/{action_id}"
    # Hover, then lock in. The client answers OK and still keeps the turn open at times, so the
    # tries take turns between the two ways of locking in until the session shows it done
    if tries % 2 == 0:
        hovered = _lcu("PATCH", path, {"championId": champion}) is not None
        done = hovered and _lcu("POST", path + "/complete") is not None
    else:
        done = _lcu("PATCH", path, {"championId": champion, "completed": True}) is not None
    if not done:
        log.warning(f"[Auto] Could not {kind} {champion} (action {action_id}, try {tries + 1})")
    elif tries == 0:
        log.info(f"[Auto] {kind} {champion} sent")
    elif tries % 10 == 0:
        log.info(f"[Auto] {kind} {champion} still open after {tries} tries, trying again")
    return FAST_S if _dodge["armed"] else BUSY_S


# ---- dodging ----

DODGE_PATH = ('/lol-login/v1/session/invoke?destination=lcdsServiceProxy&method=call'
              '&args=["","teambuilder-draft","quitV2",""]')
_dodge: dict = {"armed": False, "state": "", "game": None}


def dodge_now() -> str:
    """Leave champ select without restarting the client (the usual dodge penalty applies)."""
    if _lcu("GET", "/lol-gameflow/v1/gameflow-phase") != "ChampSelect":
        return "Şu an şampiyon seçiminde değilsin"
    _dodge["armed"] = False
    if _lcu("POST", DODGE_PATH, {}) is None:
        return "Dodge atılamadı"
    log.info("[Auto] Dodged")
    _dodge["state"] = "dodged"
    return "Dodge atıldı"


def arm_dodge(on: bool) -> str:
    """Dodge in the last second of champ select (on) or not (off)."""
    if on and _lcu("GET", "/lol-gameflow/v1/gameflow-phase") != "ChampSelect":
        return "Şu an şampiyon seçiminde değilsin"
    _dodge.update(armed=bool(on), state="")
    if on:
        start(force=True)
        log.info("[Auto] Last second dodge armed")
        return "Son saniyede dodge atılacak"
    return "Son saniye dodge iptal"


def _dodge_check(session: dict) -> None:
    """The armed dodge goes when champ select is about to end."""
    if not _dodge["armed"]:
        return
    timer = session.get("timer") or {}
    left = timer.get("adjustedTimeLeftInPhase")
    if timer.get("phase") == "FINALIZATION" and isinstance(left, (int, float)) and left <= DODGE_AT_MS:
        _dodge["armed"] = False
        ok = _lcu("POST", DODGE_PATH, {}) is not None
        _dodge["state"] = "dodged" if ok else "failed"
        log.info(f"[Auto] Last second dodge {'sent' if ok else 'failed'} ({left:.0f} ms left)")


# ---- queue again after a game ----

def requeue_game(session) -> Optional[int]:
    """The game id to queue again after, or None: only matchmade games (not custom games,
    practice tool or tutorials), so the player's own lobby setup is never started by surprise."""
    if not isinstance(session, dict):
        return None
    data = session.get("gameData") or {}
    queue = data.get("queue") or {}
    if data.get("isCustomGame") or not isinstance(queue.get("id"), int) or queue["id"] <= 0:
        return None
    if queue.get("type") in ("PRACTICETOOL", "TUTORIAL") or str(queue.get("category", "")).lower() == "custom":
        return None
    game = data.get("gameId")
    return game if isinstance(game, int) and game > 0 else None


def _after_game(phase) -> bool:
    """End of game: once the stats are up, back to the lobby. In that lobby: start the queue.
    True while there is something left to do, so the thread checks more often."""
    now = time.monotonic()
    if phase == "EndOfGame":
        game = requeue_game(_lcu("GET", "/lol-gameflow/v1/session"))
        if game is None or game == _requeue["game"]:
            return False
        _requeue["game"] = game
        if _lcu("POST", "/lol-lobby/v2/play-again") is None:
            log.warning("[Auto] Could not go back to the lobby after the game")
            return False
        delay = settings().get("requeue_delay") or 0
        _requeue["not_before"] = now + delay
        _requeue["until"] = now + REQUEUE_WAIT_S + delay
        log.info(f"[Auto] Game {game} over: back to the lobby to queue again"
                 + (f" in {delay}s" if delay else ""))
        return True
    if phase in END_PHASES:
        return True  # honor vote and stats come first
    if phase != "Lobby" or now >= _requeue["until"]:
        _requeue["until"] = 0.0
        return False
    if now < _requeue["not_before"]:
        return True
    lobby = _lcu("GET", "/lol-lobby/v2/lobby")
    if not isinstance(lobby, dict):
        return True  # the lobby is still opening
    if not (lobby.get("localMember") or {}).get("isLeader", True):
        _note("requeue-leader", "[Auto] Not the party leader: the leader starts the queue")
        _requeue["until"] = 0.0
        return False
    if lobby.get("canStartActivity") is False:
        _note("requeue-wait", "[Auto] Lobby not ready to queue yet (party members or a penalty), waiting")
        return True
    if _lcu("POST", "/lol-lobby/v2/lobby/matchmaking/search") is not None:
        log.info("[Auto] Queue started again")
        _requeue["until"] = 0.0
        return False
    return True


_notes: set = set()
_last: dict = {"phase": None}


def _note(key: str, text: str) -> None:
    """Log a state once, so the log shows why nothing happened without repeating every second."""
    if key not in _notes:
        _notes.add(key)
        log.info(text)


def after_dodge(before, phase) -> bool:
    """Champ select ended back in the lobby: someone dodged."""
    return before == "ChampSelect" and phase == "Lobby"


def _queue_refresh() -> None:
    """A search well past its estimated time starts over (at most every REFRESH_EVERY_S)."""
    search = _lcu("GET", "/lol-lobby/v2/lobby/matchmaking/search-state")
    if not isinstance(search, dict) or search.get("searchState") != "Searching":
        return
    waited, estimate = search.get("timeInQueue"), search.get("estimatedQueueTime")
    if not isinstance(waited, (int, float)) or not isinstance(estimate, (int, float)) or estimate <= 0:
        return
    now = time.monotonic()
    if waited < estimate + REFRESH_OVER_S or now - _refresh["at"] < REFRESH_EVERY_S:
        return
    _refresh["at"] = now
    if _lcu("DELETE", "/lol-lobby/v2/lobby/matchmaking/search") is None:
        return
    time.sleep(1.0)
    if _lcu("POST", "/lol-lobby/v2/lobby/matchmaking/search") is not None:
        log.info(f"[Auto] Search restarted ({waited:.0f}s, estimated {estimate:.0f}s)")


def _tick() -> float:
    config = settings()
    if not _any_on(config) and not _dodge["armed"]:
        return IDLE_S
    phase = _lcu("GET", "/lol-gameflow/v1/gameflow-phase")
    before = _last["phase"]
    if phase != before:
        _last["phase"] = phase
        _notes.clear()  # a new phase may say something new
        _hovered.clear()
        log.info(f"[Auto] Phase {phase}")
        if before == "ChampSelect":
            _dodge.update(armed=False)
        if phase == "ChampSelect":
            _dodge.update(state="")
        if config["requeue_dodge"] and after_dodge(before, phase):
            now = time.monotonic()
            delay = config.get("requeue_delay") or 0
            _requeue.update(not_before=now + delay, until=now + DODGE_REQUEUE_S + delay)
            log.info("[Auto] Champ select dodged: queueing again" + (f" in {delay}s" if delay else ""))
    if phase == "ReadyCheck" and config["accept"]:
        _accept()
        return BUSY_S
    if phase == "ChampSelect" and (config["ban"] or config["pick"] or _dodge["armed"]):
        return _champ_select(config)
    _done.clear()
    if phase == "Matchmaking" and config["requeue_refresh"]:
        _queue_refresh()
        return BUSY_S
    if config["requeue_dodge"] and phase == "Lobby" and _requeue["until"] and _after_game(phase):
        return BUSY_S
    if config["requeue"] and _after_game(phase):
        return BUSY_S
    return IDLE_S


def _any_on(config) -> bool:
    return bool(config and any(config.get(key) for key in SWITCHES))


def _run() -> None:
    global _thread
    while True:
        if not _any_on(settings()) and not _dodge["armed"]:
            with _lock:
                # A switch turned on just now keeps this thread instead of starting another
                if not _any_on(_cache) and not _dodge["armed"]:
                    _thread = None
                    return
        try:
            delay = _tick()
        except Exception as exc:  # noqa: BLE001
            log.warning(f"[Auto] {exc}")
            delay = IDLE_S
        time.sleep(delay)


def start(force: bool = False) -> None:
    """Watch the client while any switch is on or a dodge is armed (the thread ends when all are off)."""
    global _thread
    if not force and not _any_on(settings()):
        return
    with _lock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_run, daemon=True, name="ParasiteAuto")
        _thread.start()
