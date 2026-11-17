import unittest
from unittest.mock import patch

from launcher import parasite_lobby as lobby


def _game(queue, lane, role="SOLO", win=True, champion=1):
    return {"queueId": queue, "participants": [{"championId": champion, "stats": {"win": win},
                                                "timeline": {"lane": lane, "role": role}}]}


class RankTests(unittest.TestCase):
    def test_solo_rank(self):
        stats = {"queueMap": {"RANKED_SOLO_5x5": {"tier": "DIAMOND", "division": "I", "leaguePoints": 73,
                                                  "wins": 6, "losses": 1}}}
        self.assertEqual(lobby.parse_rank(stats), {"tier": "Elmas", "division": "I", "lp": 73, "wins": 6, "losses": 1})

    def test_apex_has_no_division(self):
        stats = {"queueMap": {"RANKED_SOLO_5x5": {"tier": "MASTER", "division": "NA", "leaguePoints": 536}}}
        self.assertEqual(lobby.parse_rank(stats)["division"], "")

    def test_unranked(self):
        self.assertIsNone(lobby.parse_rank({"queueMap": {"RANKED_SOLO_5x5": {"tier": "NONE"}}}))
        self.assertIsNone(lobby.parse_rank(None))

    def test_flex_queue(self):
        self.assertEqual(lobby._ranked_queue(440), "RANKED_FLEX_SR")
        self.assertEqual(lobby._ranked_queue(420), "RANKED_SOLO_5x5")


class HistoryTests(unittest.TestCase):
    def test_roles_and_off_role(self):
        games = [_game(420, "BOTTOM", "SUPPORT")] * 6 + [_game(420, "TOP", win=False)] + [_game(450, "MIDDLE")]
        parsed = lobby.parse_history({"games": {"games": games}})
        self.assertEqual(parsed["roles"], {"utility": 6, "top": 1})
        self.assertEqual((parsed["recentWins"], parsed["recentLosses"]), (6, 1))
        self.assertEqual(lobby.main_role(parsed["roles"]), "utility")
        self.assertTrue(lobby.off_role("top", parsed["roles"]))
        self.assertFalse(lobby.off_role("utility", parsed["roles"]))

    def test_too_few_games_is_never_off_role(self):
        self.assertFalse(lobby.off_role("top", {"utility": 3}))
        self.assertIsNone(lobby.main_role({"utility": 3}))


class TeamTests(unittest.TestCase):
    def test_rows_take_names_from_reveal(self):
        session = {"localPlayerCellId": 1, "myTeam": [
            {"cellId": 1, "puuid": "b", "assignedPosition": "JUNGLE", "championId": 62},
            {"cellId": 0, "puuid": "a", "assignedPosition": "top", "championId": 0, "championPickIntent": 86},
        ]}
        revealed = [{"puuid": "a", "gameName": "Top", "gameTag": "TR1", "opggUrl": "x"},
                    {"puuid": "b", "gameName": "Me", "gameTag": "EUW"}]
        rows = lobby.team_rows(session, revealed)
        self.assertEqual([r["gameName"] for r in rows], ["Top", "Me"])
        self.assertEqual(rows[0]["championId"], 86)
        self.assertTrue(rows[0]["hover"])
        self.assertEqual(rows[1]["position"], "jungle")
        self.assertTrue(rows[1]["me"])

    def test_hidden_lanes_go_to_the_players_who_play_them(self):
        session = {"localPlayerCellId": 2, "myTeam": [
            {"cellId": 0, "puuid": "x0", "assignedPosition": "top"},
            {"cellId": 1, "puuid": "x1", "assignedPosition": "middle"},
            {"cellId": 2, "puuid": "me", "assignedPosition": "bottom"},
        ]}
        revealed = [{"puuid": p, "gameName": p} for p in ("me", "mid", "top")]
        roles = {"mid": {"middle": 15, "top": 1}, "top": {"top": 12}}
        rows = lobby.team_rows(session, revealed, roles)
        self.assertEqual([(r["position"], r["gameName"], r["guessed"]) for r in rows],
                         [("top", "top", True), ("middle", "mid", True), ("bottom", "me", False)])
        self.assertFalse(any(lobby.off_role(r["position"], roles.get(r["puuid"], {})) for r in rows))

    def test_history_keeps_one_entry_per_champ_select(self):
        lobby_a = {"gameId": 7, "queueName": "Ranked Solo/Duo", "links": {}, "rows": [
            {"gameName": "A", "gameTag": "1", "position": "top", "championId": 0, "me": False}]}
        first = lobby.merge_history([], lobby.history_entry(lobby_a, now=100))
        lobby_a["rows"][0]["championId"] = 86
        second = lobby.merge_history(first, lobby.history_entry(lobby_a, now=200))
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["at"], 100)
        self.assertEqual(second[0]["players"][0]["championId"], 86)


def _action(id_, cell, kind="pick", champion=0, completed=False):
    return {"id": id_, "actorCellId": cell, "type": kind, "championId": champion, "completed": completed}


def _draft(*actions, me=1, bans=None):
    return {"localPlayerCellId": me, "myTeam": [{"cellId": me}], "actions": [list(actions)], "bans": bans or {}}


class HoverTests(unittest.TestCase):
    def test_hovers_on_your_next_pick_before_or_during_your_turn(self):
        self.assertEqual(lobby.hover_action(_draft(_action(3, 1, "ban"), _action(7, 1)), 59), (7, ""))
        # A teammate hovering it doesn't stop you; only locked-in picks and bans do
        self.assertEqual(lobby.hover_action(_draft(_action(8, 2, champion=59), _action(9, 1)), 59), (9, ""))

    def test_says_why_a_champion_cannot_be_hovered(self):
        draft = _draft(_action(3, 2, "ban", 59, completed=True), _action(7, 1))
        self.assertEqual(lobby.hover_action(draft, 59), (None, lobby.HOVER_TAKEN))
        self.assertEqual(lobby.hover_action(draft, 64, {104}), (None, lobby.HOVER_UNAVAILABLE))
        self.assertEqual(lobby.hover_action(draft, 104, {104}), (7, ""))
        self.assertEqual(lobby.hover_action(_draft(_action(7, 1), bans={"theirTeamBans": [64]}), 64),
                         (None, lobby.HOVER_TAKEN))
        self.assertEqual(lobby.hover_action(_draft(_action(7, 1, champion=104, completed=True)), 59),
                         (None, lobby.HOVER_LOCKED_IN))
        self.assertEqual(lobby.hover_action(_draft(_action(8, 2)), 59), (None, lobby.HOVER_NO_PICK))

    def test_hover_patches_the_pick_without_locking_it_in(self):
        calls = []

        def lcu(method, path, body=None):
            calls.append((method, path, body))
            if path == "/lol-champ-select/v1/session":
                return _draft(_action(7, 1))
            if path == "/lol-champ-select/v1/pickable-champion-ids":
                return []
            return {}
        with patch("launcher.parasite_auto._lcu", side_effect=lcu):
            message = lobby.hover(59, "Jarvan IV")
        self.assertEqual(calls[-1], ("PATCH", "/lol-champ-select/v1/session/actions/7", {"championId": 59}))
        self.assertIn("kilitlenmedi", message)
        self.assertTrue(lobby.hover_state()["ok"])

    def test_hover_outside_champ_select_or_refused(self):
        with patch("launcher.parasite_auto._lcu", return_value=None):
            self.assertEqual(lobby.hover(59, "Jarvan IV"), "Şampiyon seçiminde değilsin.")
        state = lobby.hover_state()
        self.assertEqual((state["id"], state["ok"]), (59, False))

        def lcu(method, path, body=None):
            return [104] if path.endswith("pickable-champion-ids") else _draft(_action(7, 1))
        with patch("launcher.parasite_auto._lcu", side_effect=lcu):
            self.assertEqual(lobby.hover(59, "Jarvan IV"), "Jarvan IV seçilemez: sende yok ya da banlı.")
        self.assertEqual(lobby.hover("59"), "")


if __name__ == "__main__":
    unittest.main()
