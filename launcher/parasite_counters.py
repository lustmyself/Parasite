"""Counters for the enemy picks in champ select, shown in the hub's Reveal page.

For each enemy pick: the champions that beat it most in its lane in Master+ games (every
region, Ranked Solo/Duo), with their win rate, how much better than expected that is, and
U.GG's gold, CS and kill leads at 15 minutes; and how the teammate in that lane fares
against it. The numbers are the public JSON U.GG's and Lolalytics' own pages load (no key
needed); both are read and averaged, so a counter both sites back ranks first. Each enemy
links to its counter pages on U.GG, Lolalytics, LadderEye and League of Graphs.

Nothing runs while the hub isn't showing the page: the page's polling asks for the board,
which looks at the champ select at most every couple of seconds and computes in the
background when the enemy picks change.
"""

from __future__ import annotations

import itertools
import math
import threading
import time
from typing import Optional

from utils.core.logging import get_logger

log = get_logger()

UGG_STATS = "https://stats2.u.gg/lol/1.5"
UGG_PATCHES = "https://static.bigbrain.gg/assets/lol/riot_patch_update/prod/ugg/patches.json"
UGG_VERSIONS = "https://static.bigbrain.gg/assets/lol/riot_patch_update/prod/ugg/ugg-api-versions.json"
UGG_DEFAULT_VERSION = "1.5.0"
LOLALYTICS_COUNTERS = "https://a1.lolalytics.com/mega/?ep=counter&v=1"
WORLD, MASTER_PLUS = "12", "14"
# A new patch has too few Master+ games for matchups at first: keep the previous one until then
MIN_PATCH_GAMES = 100_000
CACHE_S = 6 * 3600
TIMEOUT_S = 20
COUNTERS = 8
# A counter needs this share of the enemy's games in the lane, between the two limits
GAMES_SHARE, MIN_GAMES, MIN_SPARSE_GAMES = 0.025, 200, 50
# Matchup win rates are pulled towards the average against the enemy as if by this many games
SHRINK = 400
POLL_S = 2.0

ROLES = ("top", "jungle", "middle", "bottom", "utility")
UGG_ROLE_ID = {"jungle": "1", "utility": "2", "bottom": "3", "top": "4", "middle": "5"}
UGG_RANKING_KEY = {"top": "top", "jungle": "jungle", "middle": "mid", "bottom": "adc", "utility": "supp"}
UGG_ROLE_NAME = {"top": "top", "jungle": "jungle", "middle": "mid", "bottom": "adc", "utility": "support"}
LOLALYTICS_LANE = {"top": "top", "jungle": "jungle", "middle": "middle", "bottom": "bottom", "utility": "support"}
LOG_ROLE = {"top": "top", "jungle": "jungle", "middle": "mid", "bottom": "adc", "utility": "support"}
ROLE_LABEL = {"top": "Üst", "jungle": "Orman", "middle": "Orta", "bottom": "Alt", "utility": "Destek"}

_lock = threading.Lock()
_cache: dict = {}  # url -> (time, json)
_state: dict = {"key": None, "board": {"status": "idle"}, "checked": 0.0, "busy": False, "phase": None,
                "session": None}


# ---- downloads ----

def _get_json(url: str):
    now = time.time()
    with _lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < CACHE_S:
            return hit[1]
    import requests
    from config import APP_USER_AGENT
    response = requests.get(url, timeout=TIMEOUT_S, headers={"User-Agent": APP_USER_AGENT})
    response.raise_for_status()
    data = response.json()
    with _lock:
        _cache[url] = (now, data)
    return data


def parse_ranking(value) -> tuple[dict, float]:
    """U.GG's champion ranking: {role: {champion: (wins, games)}} and the patch's game count."""
    roles = value[0] if isinstance(value, list) and value and isinstance(value[0], dict) else {}
    records = {}
    for role in ROLES:
        records[role] = {}
        for row in roles.get(UGG_RANKING_KEY[role]) or []:
            try:
                records[role][int(row[0])] = (float(row[2]), float(row[3]))
            except (TypeError, ValueError, IndexError):
                continue
    games = value[3] if isinstance(value, list) and len(value) > 3 and isinstance(value[3], (int, float)) else 0
    return records, float(games)


def parse_ugg_matchups(value) -> dict:
    """U.GG's matchups of one champion: {role: {opponent: row}}, rows from the opponent's side
    (its wins, games and leads at 15 summed over the games)."""
    try:
        tier = value[WORLD][MASTER_PLUS]
    except (KeyError, TypeError):
        return {}
    out = {}
    for role in ROLES:
        rows = {}
        try:
            entries = tier[UGG_ROLE_ID[role]][0]
        except (KeyError, IndexError, TypeError):
            entries = []
        for row in entries or []:
            try:
                games = float(row[2])
                if games <= 0:
                    continue
                rows[int(row[0])] = {"wins": float(row[1]), "games": games,
                                     "gold": float(row[4]), "cs": float(row[6]), "kills": float(row[9])}
            except (TypeError, ValueError, IndexError):
                continue
        out[role] = rows
    return out


def parse_lolalytics(value) -> dict:
    """Lolalytics' counters of one champion in one lane, turned to the opponent's side:
    {opponent: {wins, games, delta}}."""
    rows = {}
    for counter in (value or {}).get("counters") or []:
        try:
            games = float(counter["n"])
            if games <= 0:
                continue
            delta = counter.get("d2")
            rows[int(counter["cid"])] = {"wins": (100.0 - float(counter["vsWr"])) / 100.0 * games, "games": games,
                                         "delta": -float(delta) if isinstance(delta, (int, float)) else None}
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def _patch_stats() -> dict:
    patches = _get_json(UGG_PATCHES)
    try:
        versions = _get_json(UGG_VERSIONS)
    except Exception:  # noqa: BLE001 - only names file versions, 1.5.0 for years
        versions = {}

    def version(patch, kind):
        value = (versions.get(patch) or {}).get(kind) if isinstance(versions, dict) else None
        return value if isinstance(value, str) else UGG_DEFAULT_VERSION

    best = None
    for patch in list(patches or [])[:2]:
        url = f"{UGG_STATS}/champion_ranking/world/{patch}/ranked_solo_5x5/master_plus/{version(patch, 'champion_ranking')}.json"
        try:
            records, games = parse_ranking(_get_json(url))
        except Exception as exc:  # noqa: BLE001
            log.info(f"[Counters] No U.GG ranking for patch {patch}: {exc}")
            continue
        stats = {"patch": patch, "matchups": version(patch, "matchups"), "records": records, "games": games}
        if games >= MIN_PATCH_GAMES:
            return stats
        if best is None or games > best["games"]:
            best = stats
    if best is None:
        raise RuntimeError("U.GG has no Master+ stats for the latest patches")
    return best


def display_patch(patch: str) -> str:
    """U.GG's "16_21" is Riot's 26.21 (patches are named by year since 15.x)."""
    major, _, minor = patch.partition("_")
    try:
        number = int(major)
    except ValueError:
        return patch
    return f"{number + 10 if number >= 15 else number}.{minor}"


# ---- math ----

def _record(stats, role, champion):
    record = stats["records"].get(role, {}).get(champion)
    return record if record and record[1] > 0 else None


def _win_rate(stats, role, champion) -> Optional[float]:
    record = _record(stats, role, champion)
    return record[0] / record[1] if record else None


def role_share(stats, champion, role) -> float:
    games = {r: (_record(stats, r, champion) or (0, 0))[1] for r in ROLES}
    return (games[role] + 1) / (sum(games.values()) + len(ROLES))


def assign_roles(enemies: list, stats) -> list:
    """Each enemy's lane: the one League shows, else the free lane that best fits how the
    unplaced picks are usually played, so two picks never share one."""
    roles = [e.get("role") for e in enemies]
    free = [r for r in ROLES if r not in roles]
    unplaced = [i for i, r in enumerate(roles) if r is None]
    best = None
    for order in itertools.permutations(free, min(len(free), len(unplaced))):
        score = sum(math.log(role_share(stats, enemies[i]["id"], role)) for i, role in zip(unplaced, order))
        if best is None or score > best[0]:
            best = (score, order)
    if best:
        for i, role in zip(unplaced, best[1]):
            roles[i] = role
    return roles


def _side(row, role, enemy, stats) -> dict:
    """A matchup from the side of the row's champion against *enemy*."""
    win_rate = row["wins"] / row["games"]
    delta = row.get("delta")
    if delta is None:
        own, theirs = _win_rate(stats, role, row["champion"]), _win_rate(stats, role, enemy)
        if own is not None and theirs is not None:
            delta = (win_rate - (0.5 + own - theirs)) * 100
    side = {"games": int(round(row["games"])), "winRate": round(win_rate * 100, 1),
            "delta": round(delta, 1) if delta is not None else None}
    if "gold" in row:
        side.update(gold15=round(row["gold"] / row["games"]), cs15=round(row["cs"] / row["games"], 1),
                    kills15=round(row["kills"] / row["games"], 2))
    return side


def counters_for(enemy: int, role: str, stats, ugg: Optional[dict], lola: Optional[dict], names: dict) -> list:
    """The best counters to *enemy* in *role*, averaged over the sites that loaded."""
    sources = [s for s in (lola, ugg) if s is not None]
    if not sources:
        return []
    record = _record(stats, role, enemy)
    min_games = min(max((record[1] if record else 0) * GAMES_SHARE, MIN_SPARSE_GAMES), MIN_GAMES)
    theirs = _win_rate(stats, role, enemy)
    average = (1 - theirs) * 100 if theirs is not None else 50.0
    candidates = {c for s in sources for c, row in s.items() if row["games"] >= min_games and c != enemy}
    ranked = []
    for champion in candidates:
        sides = {}
        for name, source in (("lolalytics", lola), ("ugg", ugg)):
            row = (source or {}).get(champion)
            if row and row["games"] >= min_games:
                sides[name] = _side(dict(row, champion=champion), role, enemy, stats)
        if not sides:
            continue
        shrunk = [(s["games"] * s["winRate"] + SHRINK * average) / (s["games"] + SHRINK) for s in sides.values()]
        score = (sum(shrunk) + (len(sources) - len(sides)) * average) / len(sources)
        main = sides.get("lolalytics") or sides["ugg"]
        leads = sides.get("ugg") or {}
        ranked.append((score, {
            "id": champion, "name": names.get(champion, {}).get("name", f"#{champion}"),
            "slug": names.get(champion, {}).get("slug", ""),
            "winRate": main["winRate"], "delta": main["delta"], "games": main["games"],
            "gold15": leads.get("gold15"), "cs15": leads.get("cs15"), "kills15": leads.get("kills15"),
            "lolaWin": (sides.get("lolalytics") or {}).get("winRate"), "uggWin": leads.get("winRate"),
            "sites": len(sides),
        }))
    ranked.sort(key=lambda item: -item[0])
    return [counter for _, counter in ranked[:COUNTERS]]


# ---- links ----

def slug(alias: str) -> str:
    alias = (alias or "").lower()
    return "wukong" if alias == "monkeyking" else alias


def links(champion_slug: str, role: str) -> dict:
    if not champion_slug:
        return {}
    ladder = "monkeyking" if champion_slug == "wukong" else champion_slug
    return {
        "ugg": f"https://u.gg/lol/champions/{champion_slug}/counter?role={UGG_ROLE_NAME[role]}&rank=master_plus",
        "lolalytics": f"https://lolalytics.com/lol/{champion_slug}/counters/?lane={LOLALYTICS_LANE[role]}&tier=master_plus",
        "laddereye": f"https://laddereye.com/champions/{ladder}?position={role.upper()}",
        "log": f"https://www.leagueofgraphs.com/champions/counters/{champion_slug}/{LOG_ROLE[role]}/master/sr-ranked",
    }


def matchup_link(champion_slug: str, enemy_slug: str, role: str) -> str:
    if not champion_slug or not enemy_slug:
        return ""
    return f"https://u.gg/lol/champions/{champion_slug}/build/{UGG_ROLE_NAME[role]}?opp={enemy_slug}&rank=master_plus"


# ---- the board ----

def _names() -> dict:
    from launcher import parasite_skins
    return {c["id"]: {"name": c["name"], "slug": slug(c.get("alias", ""))} for c in parasite_skins.champions()}


def picks(session: dict) -> tuple[list, list]:
    """(enemies, allies) as [{id, role}]: champions picked or shown, lanes League shows."""
    def team(key):
        out = []
        for member in (session or {}).get(key) or []:
            champion = member.get("championId") or 0
            if not isinstance(champion, int) or champion <= 0:
                continue
            role = str(member.get("assignedPosition") or "").lower()
            out.append({"id": champion, "role": role if role in ROLES else None})
        return out
    return team("theirTeam"), team("myTeam")


def build_board(enemies: list, allies: list) -> dict:
    stats = _patch_stats()
    names = _names()
    roles = assign_roles(enemies, stats)
    ally_by_role = {a["role"]: a["id"] for a in allies if a["role"]}
    board = []
    for enemy, role in zip(enemies, roles):
        cid = enemy["id"]
        ugg = lola = None
        try:
            ugg = parse_ugg_matchups(_get_json(
                f"{UGG_STATS}/matchups/{stats['patch']}/ranked_solo_5x5/{cid}/{stats['matchups']}.json")).get(role)
        except Exception as exc:  # noqa: BLE001
            log.info(f"[Counters] U.GG has no matchups for {cid}: {exc}")
        enemy_slug = names.get(cid, {}).get("slug", "")
        if enemy_slug:
            try:
                lola = parse_lolalytics(_get_json(
                    f"{LOLALYTICS_COUNTERS}&c={enemy_slug}&lane={LOLALYTICS_LANE[role]}&vslane={LOLALYTICS_LANE[role]}"
                    f"&tier=master_plus&queue=ranked&region=all"))
            except Exception as exc:  # noqa: BLE001
                log.info(f"[Counters] Lolalytics has no counters for {enemy_slug}: {exc}")
        entry = {"id": cid, "name": names.get(cid, {}).get("name", f"#{cid}"), "slug": enemy_slug,
                 "role": role, "roleLabel": ROLE_LABEL.get(role, ""), "links": links(enemy_slug, role),
                 "counters": counters_for(cid, role, stats, ugg, lola, names)}
        for counter in entry["counters"]:
            counter["link"] = matchup_link(counter["slug"], enemy_slug, role)
        ally = ally_by_role.get(role)
        if ally:
            row = (lola or {}).get(ally) or (ugg or {}).get(ally)
            leads = (ugg or {}).get(ally)
            side = _side(dict(row, champion=ally), role, cid, stats) if row else {}
            if leads:
                ugg_side = _side(dict(leads, champion=ally), role, cid, stats)
                side.update({k: ugg_side[k] for k in ("gold15", "cs15", "kills15")})
            entry["ally"] = {"id": ally, "name": names.get(ally, {}).get("name", f"#{ally}"), **side,
                             "link": matchup_link(names.get(ally, {}).get("slug", ""), enemy_slug, role)}
        board.append(entry)
    return {"status": "ready", "patch": display_patch(stats["patch"]), "enemies": board}


def _compute(key, enemies, allies) -> None:
    try:
        board = build_board(enemies, allies)
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[Counters] Could not load the counters: {exc}")
        board = {"status": "error", "enemies": [
            {"id": e["id"], "name": _names().get(e["id"], {}).get("name", ""), "role": e.get("role"),
             "links": links(_names().get(e["id"], {}).get("slug", ""), e.get("role") or "middle"), "counters": []}
            for e in enemies]}
    with _lock:
        if _state["key"] == key:
            _state["board"] = board
        _state["busy"] = False


def board() -> dict:
    """The counters board for the hub; looks at the champ select at most every POLL_S."""
    now = time.monotonic()
    with _lock:
        due = now - _state["checked"] >= POLL_S and not _state["busy"]
        if due:
            _state["checked"] = now
    if due:
        from launcher import parasite_auto
        phase = parasite_auto._lcu("GET", "/lol-gameflow/v1/gameflow-phase")
        session = parasite_auto._lcu("GET", "/lol-champ-select/v1/session") if phase == "ChampSelect" else None
        enemies, allies = picks(session) if isinstance(session, dict) else ([], [])
        key = (tuple((e["id"], e["role"]) for e in enemies), tuple((a["id"], a["role"]) for a in allies))
        with _lock:
            _state["phase"] = phase if isinstance(phase, str) else None
            _state["session"] = session if isinstance(session, dict) else None
            if not enemies:
                _state.update(key=None, board={"status": "idle"})
            elif key != _state["key"]:
                _state.update(key=key, busy=True, board=dict(_state["board"], status="loading"))
                threading.Thread(target=_compute, args=(key, enemies, allies), daemon=True,
                                 name="ParasiteCounters").start()
    with _lock:
        return dict(_state["board"], phase=_state["phase"])


def session() -> Optional[dict]:
    """The champ select session board() last read."""
    with _lock:
        return _state["session"]
