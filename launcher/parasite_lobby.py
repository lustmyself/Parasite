"""The champ select lobby for the hub's Champ select page.

One row per teammate: their Riot ID (from Lobby Reveal, since ranked hides it), lane, rank
with LP and wins/losses, the champion they picked or hover, and whether the lane is off their
usual role (from their last games). The page pairs each row with the enemy in that lane from
the counters board. Every champ select with names is kept in a history file
(parasite-reveal-history.json), newest first.

Rank, icon and recent games come from the League client (LCU) in a background thread and are
kept for a few minutes per player, so the page's polling never waits on them.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from utils.core.logging import get_logger

log = get_logger()

ROLES = ("top", "jungle", "middle", "bottom", "utility")
QUEUES = {400: "Normal Draft", 420: "Ranked Solo/Duo", 430: "Normal Blind", 440: "Ranked Flex",
          450: "ARAM", 490: "Quickplay", 700: "Clash", 1700: "Arena"}
FLEX_QUEUES = {440}
SR_QUEUES = {400, 420, 430, 440, 490, 700}
APEX = {"MASTER", "GRANDMASTER", "CHALLENGER"}
RECENT_GAMES = 20
OFF_ROLE_MIN_GAMES = 5
OFF_ROLE_SHARE = 0.15
STATS_TTL_S = 10 * 60
HISTORY_FILE = "parasite-reveal-history.json"
HISTORY_MAX = 50
LANE_ROLES = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "middle", "MID": "middle", "BOTTOM": "bottom",
              "BOT": "bottom", "UTILITY": "utility", "SUPPORT": "utility"}

_lock = threading.Lock()
_stats: dict = {}  # (puuid, ranked queue) -> (time, stats)
_wanted: list = []
_worker: dict = {"thread": None}
_game: dict = {"id": None, "queue": None}
_history: dict = {"items": None, "saved": ""}


# ---- reading the client's answers ----

def parse_rank(ranked_stats, queue_type: str = "RANKED_SOLO_5x5") -> Optional[dict]:
    """Tier, division, LP and wins/losses in *queue_type*; None when unranked there."""
    entry = ((ranked_stats or {}).get("queueMap") or {}).get(queue_type) or {}
    tier = str(entry.get("tier") or "").upper()
    if not tier or tier == "NONE":
        return None
    division = str(entry.get("division") or "")
    return {"tier": tier.title(), "division": "" if tier in APEX or division == "NA" else division,
            "lp": int(entry.get("leaguePoints") or 0), "wins": int(entry.get("wins") or 0),
            "losses": int(entry.get("losses") or 0)}


def game_role(participant: dict) -> Optional[str]:
    """The lane a match history participant played."""
    for key in ("teamPosition", "individualPosition"):
        role = LANE_ROLES.get(str(participant.get(key) or "").upper())
        if role:
            return role
    timeline = participant.get("timeline") or {}
    lane = LANE_ROLES.get(str(timeline.get("lane") or "").upper())
    if lane == "bottom" and "SUPPORT" in str(timeline.get("role") or "").upper():
        return "utility"
    return lane


def parse_history(data) -> dict:
    """Lanes, wins and losses of the player's recent Summoner's Rift games."""
    games = ((data or {}).get("games") or {}).get("games") or []
    roles, wins, losses, champions = Counter(), 0, 0, []
    for game in games:
        if game.get("queueId") not in SR_QUEUES:
            continue
        participant = (game.get("participants") or [{}])[0]
        role = game_role(participant)
        if role:
            roles[role] += 1
        if (participant.get("stats") or {}).get("win"):
            wins += 1
        else:
            losses += 1
        champion = participant.get("championId")
        if isinstance(champion, int) and champion > 0 and champion not in champions:
            champions.append(champion)
    return {"roles": dict(roles), "recentWins": wins, "recentLosses": losses, "recentChampions": champions[:3]}


def main_role(roles: dict) -> Optional[str]:
    if not roles or sum(roles.values()) < OFF_ROLE_MIN_GAMES:
        return None
    return max(roles, key=roles.get)


def off_role(position: str, roles: dict) -> bool:
    """Whether *position* is a lane the player rarely plays."""
    total = sum((roles or {}).values())
    if position not in ROLES or total < OFF_ROLE_MIN_GAMES:
        return False
    return roles.get(position, 0) / total < OFF_ROLE_SHARE


def rank_text(rank: Optional[dict]) -> str:
    if not rank:
        return "Unranked"
    return f"{rank['tier']} {rank['division']}".strip() + f" · {rank['lp']} LP"


# ---- the team ----

def team_rows(session: dict, revealed: list) -> list:
    """The teammates in pick order, with names from Lobby Reveal where League hides them."""
    members = sorted((session or {}).get("myTeam") or [], key=lambda m: m.get("cellId", 99))
    local = (session or {}).get("localPlayerCellId")
    by_puuid = {p.get("puuid"): p for p in revealed or [] if p.get("puuid")}
    unmatched = [p for p in revealed or [] if p.get("puuid") not in {m.get("puuid") for m in members}]
    rows = []
    for member in members:
        puuid = member.get("puuid") or ""
        player = by_puuid.get(puuid)
        if player is None and not member.get("gameName") and unmatched:
            player = unmatched.pop(0)
            puuid = puuid or player.get("puuid") or ""
        player = player or {}
        position = str(member.get("assignedPosition") or "").lower()
        champion = member.get("championId") or 0
        intent = member.get("championPickIntent") or 0
        rows.append({
            "cell": member.get("cellId"), "me": member.get("cellId") == local, "puuid": puuid,
            "position": position if position in ROLES else "",
            "gameName": player.get("gameName") or member.get("gameName") or "",
            "gameTag": player.get("gameTag") or member.get("tagLine") or "",
            "championId": champion if isinstance(champion, int) and champion > 0 else
            (intent if isinstance(intent, int) and intent > 0 else 0),
            "hover": not (isinstance(champion, int) and champion > 0),
            "opggUrl": player.get("opggUrl", ""), "uggUrl": player.get("uggUrl", ""),
            "poroUrl": player.get("poroUrl", ""),
        })
    return rows


def _ranked_queue(queue: Optional[int]) -> str:
    return "RANKED_FLEX_SR" if queue in FLEX_QUEUES else "RANKED_SOLO_5x5"


def _fetch(puuid: str, queue_type: str) -> dict:
    from launcher.parasite_auto import _lcu
    out = {"rank": parse_rank(_lcu("GET", f"/lol-ranked/v1/ranked-stats/{puuid}"), queue_type)}
    summoner = _lcu("GET", f"/lol-summoner/v2/summoners/puuid/{puuid}") or {}
    out["iconId"] = summoner.get("profileIconId") if isinstance(summoner, dict) else None
    out.update(parse_history(_lcu(
        "GET", f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex={RECENT_GAMES - 1}")))
    return out


def _work() -> None:
    while True:
        with _lock:
            if not _wanted:
                _worker["thread"] = None
                return
            key = _wanted.pop(0)
        try:
            stats = _fetch(*key)
        except Exception as exc:  # noqa: BLE001
            log.debug(f"[Lobby] Could not read a teammate's stats: {exc}")
            stats = {}
        with _lock:
            _stats[key] = (time.monotonic(), stats)


def _stats_for(puuid: str, queue_type: str) -> Optional[dict]:
    """Cached stats, or None while they load (the load starts here)."""
    if not puuid:
        return None
    key = (puuid, queue_type)
    with _lock:
        hit = _stats.get(key)
        if hit and time.monotonic() - hit[0] < STATS_TTL_S:
            return hit[1]
        if key not in _wanted:
            _wanted.append(key)
        if _worker["thread"] is None:
            _worker["thread"] = threading.Thread(target=_work, daemon=True, name="ParasiteLobby")
            _worker["thread"].start()
    return hit[1] if hit else None


def _queue(session: dict) -> Optional[int]:
    game = (session or {}).get("gameId") or 0
    if _game["id"] == game and _game["queue"] is not None:
        return _game["queue"]
    from launcher.parasite_auto import _lcu
    flow = _lcu("GET", "/lol-gameflow/v1/session") or {}
    queue = (((flow.get("gameData") or {}).get("queue") or {}).get("id")) if isinstance(flow, dict) else None
    _game.update(id=game, queue=queue if isinstance(queue, int) else None)
    return _game["queue"]


def snapshot(session: Optional[dict], reveal: dict) -> dict:
    """The page's champ select team; empty outside champ select."""
    if not isinstance(session, dict) or not session.get("myTeam"):
        return {"active": False, "rows": []}
    queue = _queue(session)
    queue_type = _ranked_queue(queue)
    rows = team_rows(session, (reveal or {}).get("players") or [])
    for row in rows:
        stats = _stats_for(row["puuid"], queue_type)
        row["loading"] = stats is None and bool(row["puuid"])
        stats = stats or {}
        row.update(rank=stats.get("rank"), iconId=stats.get("iconId"), recentWins=stats.get("recentWins"),
                   recentLosses=stats.get("recentLosses"), recentChampions=stats.get("recentChampions") or [],
                   mainRole=main_role(stats.get("roles") or {}), offRole=off_role(row["position"], stats.get("roles") or {}))
    found = sum(1 for row in rows if row["gameName"])
    out = {"active": True, "gameId": session.get("gameId"), "queue": queue, "queueName": QUEUES.get(queue, ""),
           "rows": rows, "found": found, "total": len(rows),
           "links": {"opgg": reveal.get("multiUrl", ""), "porofessor": reveal.get("poroUrl", ""),
                     "ugg": reveal.get("uggUrl", "")}}
    if found and out["gameId"]:
        remember(out)
    return out


# ---- history ----

def _history_path() -> Path:
    from utils.core.paths import get_user_data_dir
    return get_user_data_dir() / HISTORY_FILE


def history() -> list:
    with _lock:
        if _history["items"] is None:
            try:
                items = json.loads(_history_path().read_text(encoding="utf-8"))
                _history["items"] = items if isinstance(items, list) else []
            except (OSError, ValueError):
                _history["items"] = []
        return list(_history["items"])


def history_entry(lobby: dict, now: Optional[float] = None) -> dict:
    return {
        "gameId": lobby.get("gameId"), "at": int(now if now is not None else time.time()),
        "queueName": lobby.get("queueName", ""), "links": lobby.get("links") or {},
        "players": [{"gameName": r["gameName"], "gameTag": r["gameTag"], "position": r["position"],
                     "championId": r["championId"], "me": r["me"], "rank": r.get("rank"),
                     "opggUrl": r.get("opggUrl", "")} for r in lobby.get("rows") or [] if r["gameName"]],
    }


def merge_history(items: list, entry: dict) -> list:
    """*entry* first; it replaces an earlier entry of the same champ select, keeping its time."""
    same = next((i for i in items if entry.get("gameId") and i.get("gameId") == entry["gameId"]), None)
    if same:
        entry = dict(entry, at=same.get("at", entry["at"]))
    rest = [i for i in items if i is not same]
    return ([entry] + rest)[:HISTORY_MAX]


def remember(lobby: dict) -> None:
    items = history()
    entry = history_entry(lobby)
    merged = merge_history(items, entry)
    text = json.dumps(merged, ensure_ascii=False)
    with _lock:
        if text == _history["saved"]:
            return
        _history.update(items=merged, saved=text)
    try:
        _history_path().write_text(text, encoding="utf-8")
    except OSError as exc:
        log.debug(f"[Lobby] Could not save the history: {exc}")


def clear_history() -> str:
    with _lock:
        _history.update(items=[], saved="[]")
    try:
        _history_path().write_text("[]", encoding="utf-8")
    except OSError:
        return "Silinemedi"
    return ""


# ---- the League client's Reveal box ----

CLIENT_COUNTERS = 5


def lanes(lobby: dict, board: dict) -> list:
    """Each teammate's lane for the client box: rank, off-role, champion, the enemy in that
    lane and how the pick does against it."""
    enemies = {}
    for enemy in (board or {}).get("enemies") or []:
        if enemy.get("role") and enemy["role"] not in enemies:
            enemies[enemy["role"]] = enemy
    out = []
    for row in (lobby or {}).get("rows") or []:
        lane = {k: row.get(k) for k in ("puuid", "position", "championId", "hover", "offRole", "mainRole", "me", "rank")}
        enemy = enemies.get(row.get("position"))
        if enemy:
            lane["enemy"] = {"id": enemy["id"], "name": enemy.get("name", "")}
            ally = enemy.get("ally") or {}
            if ally.get("id") == row.get("championId") and ally.get("winRate") is not None:
                lane["matchup"] = {k: ally.get(k) for k in ("winRate", "games", "kills15", "cs15", "gold15")}
        out.append(lane)
    return out


def client_counters(board: dict) -> list:
    """The best few counters of each enemy pick, for the client box."""
    out = []
    for enemy in (board or {}).get("enemies") or []:
        out.append({"id": enemy["id"], "name": enemy.get("name", ""), "role": enemy.get("role"),
                    "roleLabel": enemy.get("roleLabel", ""),
                    "counters": [{k: c.get(k) for k in ("id", "name", "winRate", "games", "gold15", "link")}
                                 for c in (enemy.get("counters") or [])[:CLIENT_COUNTERS]]})
    return out


def enrich(payload: dict) -> dict:
    """Adds lanes, matchups and counters to Lobby Reveal's message to the client box."""
    from launcher import parasite_counters
    board = parasite_counters.board()
    lobby = snapshot(parasite_counters.session(), payload)
    return dict(payload, lanes=lanes(lobby, board), counters=client_counters(board),
                queueName=lobby.get("queueName", ""), countersLoading=board.get("status") == "loading")
