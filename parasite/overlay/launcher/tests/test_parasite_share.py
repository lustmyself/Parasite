import asyncio
import time
import unittest
import unittest.mock
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from launcher import parasite_share


class FakeLcu:
    def __init__(self, lobby=None, session=None, flow=None):
        self.lobby, self.session, self.flow = lobby, session, flow
        self.ok = True
        self.current_summoner = {"summonerId": 1, "puuid": "me-puuid", "gameName": "Me"}

    def get(self, path, timeout=1.0):
        return {"/lol-lobby/v2/lobby": self.lobby, "/lol-gameflow/v1/session": self.flow}.get(path)


def team(cell=0, side=1, size=5):
    return [{"cellId": i, "team": side, "summonerId": 10 + i, "puuid": f"p{i}"} for i in range(size)]


class RoomsTest(unittest.TestCase):
    def test_lobby_room_needs_someone_else(self):
        alone = {"partyId": "abc", "members": [{"summonerId": 1}]}
        duo = {"partyId": "abc", "members": [{"summonerId": 1}, {"summonerId": 2}]}
        self.assertIsNone(parasite_share.lobby_room(alone))
        self.assertIsNone(parasite_share.lobby_room({"members": duo["members"]}))
        self.assertRegex(parasite_share.lobby_room(duo), r"^[0-9a-f]{32}$")
        self.assertEqual(parasite_share.lobby_room(duo), parasite_share.lobby_room(dict(duo)))
        self.assertNotEqual(parasite_share.lobby_room(duo), parasite_share.lobby_room({**duo, "partyId": "xyz"}))

    def test_team_room_same_for_the_team_not_the_enemies(self):
        mine = {"gameId": 77, "localPlayerCellId": 2, "myTeam": team(side=1)}
        mate = {"gameId": 77, "localPlayerCellId": 4, "myTeam": team(side=1)}
        enemy = {"gameId": 77, "localPlayerCellId": 6, "myTeam": [
            {"cellId": 5 + i, "team": 2} for i in range(5)]}
        self.assertEqual(parasite_share.team_room(mine), parasite_share.team_room(mate))
        self.assertNotEqual(parasite_share.team_room(mine), parasite_share.team_room(enemy))
        self.assertNotEqual(parasite_share.team_room(mine), parasite_share.team_room({**mine, "gameId": 78}))

    def test_team_room_needs_a_game_and_a_team(self):
        self.assertIsNone(parasite_share.team_room({"gameId": 0, "myTeam": team()}))
        self.assertIsNone(parasite_share.team_room({"gameId": 5, "myTeam": team(size=1)}))
        self.assertIsNotNone(parasite_share.team_room({"gameId": 0, "myTeam": team()}, game_id="5"))

    def test_rooms_for_each_phase(self):
        duo = {"partyId": "abc", "members": [{}, {}]}
        lcu = FakeLcu(lobby=duo, session={"gameId": 0, "localPlayerCellId": 0, "myTeam": team()},
                      flow={"gameData": {"gameId": 9}})
        self.assertEqual(parasite_share.rooms_for(lcu, "Lobby"), {parasite_share.lobby_room(duo)})
        self.assertEqual(parasite_share.rooms_for(lcu, "ChampSelect"),
                         {parasite_share.team_room(lcu.session, 9)})
        self.assertIsNone(parasite_share.rooms_for(lcu, "InProgress"))
        self.assertEqual(parasite_share.rooms_for(lcu, "EndOfGame"), set())


class ManagerTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        for target in ("utils.core.paths.get_user_data_dir", "party.core.party_storage.get_user_data_dir"):
            patcher = patch(target, return_value=Path(self.dir.name))
            patcher.start()
            self.addCleanup(patcher.stop)
        # Riot ID / Discord in the state: tested on their own below
        quiet = patch.object(parasite_share, "_my_profile", return_value={})
        quiet.start()
        self.addCleanup(quiet.stop)

    def make(self, phase="Lobby"):
        state = SimpleNamespace(phase=phase, locked_champ_id=None, hovered_champ_id=None,
                                last_hovered_skin_id=None, selected_chroma_id=None, selected_custom_mod=None,
                                historic_mode_active=False, historic_skin_id=None, random_mode_active=False,
                                random_skin_id=None, party_manager=None)
        manager = parasite_share._manager_class()(FakeLcu(), state)
        asyncio.run(self._enable(manager))
        return manager

    async def _enable(self, manager):
        await manager.enable()
        manager._running = False
        for task in (manager._lobby_check_task, manager._skin_broadcast_task):
            task.cancel()

    def test_enable_opens_no_room(self):
        manager = self.make()
        self.assertTrue(manager.enabled)
        self.assertEqual(manager._relays, {})
        self.assertEqual(manager.my_puuid, "me-puuid")

    def test_state_carries_the_icon(self):
        manager = self.make()
        with patch.object(parasite_share, "_my_icon", return_value=4567):
            self.assertEqual(manager._current_skin_state(), {"icon_id": 4567, "puuid": "me-puuid"})
        with patch.object(parasite_share, "_my_icon", return_value=0):
            self.assertIsNone(manager._current_skin_state())

    def test_last_pick_kept_after_champ_select(self):
        manager = self.make(phase="InProgress")
        manager._skin_state = {"champion_id": 103, "skin_id": 103001, "icon_id": 1, "puuid": "x"}
        with patch.object(parasite_share, "_my_icon", return_value=0):
            self.assertEqual(manager._current_skin_state(), {"champion_id": 103, "skin_id": 103001})

    def test_shared_icons_and_no_room_following(self):
        manager = self.make()
        relay = SimpleNamespace(connected=True, members=[
            {"summoner_id": 1, "summoner_name": "Me", "skin": {"icon_id": 9}},
            {"summoner_id": 2, "summoner_name": "Duo", "skin": {"icon_id": 29, "puuid": "duo",
                                                               "rooms": ["a" * 32]}},
            {"summoner_id": 3, "summoner_name": "Plain", "skin": {"champion_id": 1, "skin_id": 1001}},
        ])
        manager._relays["k"] = relay
        self.assertEqual(manager.shared_icons(), [{"summonerId": "2", "iconId": 29, "puuid": "duo"}])
        manager._follow_advertised_rooms()
        self.assertEqual(list(manager._relays), ["k"])

    def test_sync_rooms_joins_and_leaves(self):
        manager = self.make()
        old = SimpleNamespace(disconnect=AsyncMock(), members=[], connected=True)
        manager._relays["old"] = old
        joined = []

        async def join(key):
            joined.append(key)
            manager._relays[key] = SimpleNamespace(members=[], connected=True, resume=lambda: None)

        manager._join_room = join
        asyncio.run(manager.sync_rooms({"new"}))
        old.disconnect.assert_awaited()
        self.assertEqual(joined, ["new"])
        self.assertEqual(list(manager._relays), ["new"])


class SwitchTest(unittest.TestCase):
    def test_off_without_a_relay_or_the_setting(self):
        with patch.object(parasite_share, "relay_url", return_value=""):
            self.assertFalse(parasite_share.wanted())
        with patch.object(parasite_share, "relay_url", return_value="wss://x"), \
                patch("launcher.parasite_settings.enabled", return_value=False):
            self.assertFalse(parasite_share.wanted())
        with patch.object(parasite_share, "relay_url", return_value="wss://x"), \
                patch("launcher.parasite_settings.enabled", return_value=True):
            self.assertTrue(parasite_share.wanted())

    def test_no_icons_before_start(self):
        with patch.object(parasite_share, "_runner", None):
            self.assertEqual(parasite_share.shared_icons(), [])
            self.assertEqual(parasite_share.status()["running"], False)


class FriendsTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        for target in ("utils.core.paths.get_user_data_dir", "party.core.party_storage.get_user_data_dir"):
            patcher = patch(target, return_value=Path(self.dir.name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def code(self, sid):
        from party.protocol.token_codec import create_token
        return create_token(summoner_id=sid, encryption_key=bytes([sid % 256]) * 32).encode()

    def test_pair_once_and_keep(self):
        self.assertIn("Parasite kodu değil", parasite_share.add_friend("hello"))
        self.assertIn("Eşleşildi", parasite_share.add_friend(self.code(42)))
        self.assertIn("zaten", parasite_share.add_friend(self.code(42)))
        friends = parasite_share.load_friends()["friends"]
        self.assertEqual([f["id"] for f in friends], [42])
        for sid in range(43, 43 + parasite_share.MAX_FRIENDS - 1):
            parasite_share.add_friend(self.code(sid))
        self.assertIn("En fazla", parasite_share.add_friend(self.code(99)))

    def test_code_shown_while_league_is_closed(self):
        state = SimpleNamespace(phase="None", locked_champ_id=None, hovered_champ_id=None, party_manager=None)
        manager = parasite_share._manager_class()(FakeLcu(), state)
        asyncio.run(ManagerTest._enable(None, manager))
        runner = SimpleNamespace(manager=manager, error="")
        with patch.object(parasite_share, "_runner", runner):
            code = parasite_share.status()["code"]
        self.assertTrue(code.startswith("PARASITE:"))
        runner.manager, runner.error = None, "League is not running"
        with patch.object(parasite_share, "_runner", runner):
            data = parasite_share.status()
        self.assertEqual(data["code"], code)
        self.assertEqual(data["error"], "League is not running")
        with patch.object(parasite_share, "_runner", None):
            self.assertEqual(parasite_share.status()["code"], code)

    def test_code_stays_the_same(self):
        state = SimpleNamespace(phase="None", locked_champ_id=None, hovered_champ_id=None, party_manager=None)
        manager = parasite_share._manager_class()(FakeLcu(), state)
        asyncio.run(ManagerTest._enable(None, manager))
        first = manager.code()
        with patch("time.time", return_value=time.time() + 5000):
            self.assertEqual(manager.code(), first)

    def test_own_code_refused(self):
        manager = SimpleNamespace(party_state=SimpleNamespace(my_summoner_id=7))
        with patch.object(parasite_share, "_runner", SimpleNamespace(manager=manager)):
            self.assertIn("kendi kodun", parasite_share.add_friend(self.code(7)))

    def test_remove_tells_them(self):
        parasite_share.add_friend(self.code(42))
        self.assertEqual(parasite_share.remove_friend("42"), "Arkadaş çıkarıldı")
        data = parasite_share.load_friends()
        self.assertEqual(data["friends"], [])
        self.assertEqual(data["removed"], [42])
        parasite_share.add_friend(self.code(42))
        self.assertEqual(parasite_share.load_friends()["removed"], [])

    def test_rooms_are_ours_and_the_friends(self):
        state = SimpleNamespace(phase="None", locked_champ_id=None, hovered_champ_id=None, party_manager=None)
        manager = parasite_share._manager_class()(FakeLcu(), state)
        asyncio.run(ManagerTest._enable(None, manager))
        self.assertTrue(manager._home_room)
        self.assertTrue(manager.code().startswith("PARASITE:"))
        parasite_share.add_friend(self.code(42))
        rooms = manager.pair_rooms()
        self.assertEqual(rooms, {manager._home_room, parasite_share.friend_room({"id": 42, "key": (bytes([42]) * 32).hex()})})
        self.assertEqual(manager.friends(), [{"id": "42", "name": "Arkadaş", "online": False}])
        parasite_share.remove_friend(42)
        manager.pair_rooms()
        self.assertEqual(manager._ignored_peers, {42})
        self.assertTrue(manager._need_publish)


    def test_who_pasted_our_code_is_a_friend_too(self):
        state = SimpleNamespace(phase="None", locked_champ_id=None, hovered_champ_id=None, party_manager=None)
        manager = parasite_share._manager_class()(FakeLcu(), state)
        asyncio.run(ManagerTest._enable(None, manager))
        manager._relays[manager._home_room] = SimpleNamespace(
            members=[{"summoner_id": 77, "summoner_name": "Mert"}], connected=True)
        self.assertEqual(manager.friends(), [{"id": "77", "name": "Mert", "online": True}])
        self.assertEqual(parasite_share.load_friends()["joined"], [{"id": 77, "name": "Mert"}])
        # still listed while they are away
        manager._relays[manager._home_room].members = []
        self.assertEqual(manager.friends(), [{"id": "77", "name": "Mert", "online": False}])
        with patch.object(parasite_share, "_runner", None):
            self.assertEqual(parasite_share.status()["friends"], [{"id": "77", "name": "Mert", "online": False}])
        parasite_share.remove_friend(77)
        self.assertEqual(parasite_share.load_friends()["joined"], [])
        manager._relays[manager._home_room].members = [{"summoner_id": 77, "summoner_name": "Mert"}]
        manager.pair_rooms()
        self.assertEqual(manager.friends(), [])

    def test_friends_show_riot_and_discord_seen_last(self):
        state = SimpleNamespace(phase="None", locked_champ_id=None, hovered_champ_id=None, party_manager=None)
        manager = parasite_share._manager_class()(FakeLcu(), state)
        asyncio.run(ManagerTest._enable(None, manager))
        skin = {"riot": "Mert#TR1", "dc": "Mert", "dcu": "mert_", "dca": "https://cdn.discordapp.com/embed/avatars/1.png"}
        manager._relays[manager._home_room] = SimpleNamespace(
            members=[{"summoner_id": 77, "summoner_name": "Mert", "skin": dict(skin, dca2="x")}], connected=True)
        self.assertEqual(manager.friends(), [dict({"id": "77", "name": "Mert", "online": True}, **skin)])
        manager._relays[manager._home_room].members = []
        self.assertEqual(manager.friends(), [dict({"id": "77", "name": "Mert", "online": False}, **skin)])
        # a picture from anywhere else is not shown
        self.assertEqual(parasite_share._clean_profile({"dca": "https://evil.example/x.png", "riot": "A#B"}), {"riot": "A#B"})

    def test_our_state_carries_riot_id_and_discord(self):
        lcu = SimpleNamespace(current_summoner={"gameName": "Bugra", "tagLine": "TR1"})
        user = {"name": "Bugra", "username": "lustmyself", "avatar_url": "https://cdn.discordapp.com/embed/avatars/2.png"}
        with patch("launcher.parasite_discord.user", return_value=user):
            self.assertEqual(parasite_share._my_profile(lcu), {"riot": "Bugra#TR1", "dc": "Bugra", "dcu": "lustmyself",
                                                          "dca": "https://cdn.discordapp.com/embed/avatars/2.png"})
        with patch("launcher.parasite_discord.user", return_value=None):
            self.assertEqual(parasite_share._my_profile(SimpleNamespace(current_summoner=None)), {})


class LolFriendsTest(unittest.TestCase):
    """League friends who use Parasite pair with no code."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        for target in ("utils.core.paths.get_user_data_dir", "party.core.party_storage.get_user_data_dir"):
            patcher = patch(target, return_value=Path(self.dir.name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def lcu(self, friends):
        lcu = FakeLcu()
        answers = {"/lol-chat/v1/friends": friends}
        lcu.get = lambda path, timeout=1.0: answers.get(path)
        return lcu

    FRIENDS = [
        {"puuid": "puuid-ayse", "summonerId": 21, "gameName": "Ayse", "gameTag": "TR1"},
        {"puuid": "puuid-mert", "summonerId": 22, "gameName": "Mert", "gameTag": "EUW"},
    ]

    def test_pair_room_is_the_same_from_both_sides(self):
        self.assertEqual(parasite_share.lol_pair_room("a", "b"), parasite_share.lol_pair_room("b", "a"))
        self.assertNotEqual(parasite_share.lol_pair_room("a", "b"), parasite_share.lol_pair_room("a", "c"))
        self.assertRegex(parasite_share.lol_pair_room("a", "b"), r"^[0-9a-f]{32}$")

    def test_only_hashes_reach_the_directory(self):
        asked = {}

        def ask(me, friends):
            asked.update(me=me, friends=friends)
            return [parasite_share.lol_id("puuid-ayse")]

        with patch.object(parasite_share, "_ask_directory", side_effect=ask):
            found = parasite_share.lol_friends_using_parasite(self.lcu(self.FRIENDS), "me-puuid")
        self.assertNotIn("puuid", repr(asked))
        self.assertEqual(asked["me"], parasite_share.lol_id("me-puuid"))
        self.assertEqual(list(found), [parasite_share.lol_pair_room("me-puuid", "puuid-ayse")])
        self.assertEqual(found[parasite_share.lol_pair_room("me-puuid", "puuid-ayse")]["riot"], "Ayse#TR1")

    def test_directory_down_keeps_what_we_had(self):
        with patch.object(parasite_share, "_ask_directory", return_value=None):
            self.assertIsNone(parasite_share.lol_friends_using_parasite(self.lcu(self.FRIENDS), "me-puuid"))

    def test_a_friend_never_seen_gets_a_name_from_league(self):
        state = SimpleNamespace(phase="None", locked_champ_id=None, hovered_champ_id=None, party_manager=None)
        lcu = FakeLcu()
        lcu.get = lambda path, timeout=1.0: ({"gameName": "Kislotny", "tagLine": "TR1"}
                                             if path == "/lol-summoner/v1/summoners/33" else None)
        manager = parasite_share._manager_class()(lcu, state)
        with patch.object(parasite_share, "_my_profile", return_value={}):
            asyncio.run(ManagerTest._enable(None, manager))
        parasite_share._save_friends({"friends": [], "removed": [], "joined": [{"id": 33, "name": ""}, {"id": 34, "name": ""}]})
        rows = {r["id"]: r for r in manager.friends()}
        self.assertEqual(rows["33"]["riot"], "Kislotny#TR1")
        self.assertEqual(rows["34"]["name"], "Arkadaş")
        # kept for next time
        self.assertEqual(parasite_share.load_friends()["joined"][0]["riot"], "Kislotny#TR1")

    def test_friends_are_listed_and_their_rooms_opened(self):
        state = SimpleNamespace(phase="None", locked_champ_id=None, hovered_champ_id=None, party_manager=None)
        manager = parasite_share._manager_class()(FakeLcu(), state)
        with patch.object(parasite_share, "_my_profile", return_value={}):
            asyncio.run(ManagerTest._enable(None, manager))
        room = parasite_share.lol_pair_room("me-puuid", "puuid-ayse")
        manager.lol_friends = {room: {"id": 21, "name": "Ayse", "riot": "Ayse#TR1", "puuid": "puuid-ayse"}}
        self.assertIn(room, manager.pair_rooms())
        rows = manager.friends()
        self.assertEqual([(r["id"], r["riot"], r.get("lol")) for r in rows], [("21", "Ayse#TR1", True)])
        parasite_share.remove_friend(21)
        self.assertNotIn(room, manager.pair_rooms())
        self.assertEqual(manager.friends(), [])


if __name__ == "__main__":
    unittest.main()
