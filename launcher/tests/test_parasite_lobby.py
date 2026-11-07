import unittest

from launcher import parasite_lobby as lobby


def _game(queue, lane, role="SOLO", win=True, champion=1):
    return {"queueId": queue, "participants": [{"championId": champion, "stats": {"win": win},
                                                "timeline": {"lane": lane, "role": role}}]}


class RankTests(unittest.TestCase):
    def test_solo_rank(self):
        stats = {"queueMap": {"RANKED_SOLO_5x5": {"tier": "DIAMOND", "division": "I", "leaguePoints": 73,
                                                  "wins": 6, "losses": 1}}}
        self.assertEqual(lobby.parse_rank(stats), {"tier": "Diamond", "division": "I", "lp": 73, "wins": 6, "losses": 1})

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

    def test_history_keeps_one_entry_per_champ_select(self):
        lobby_a = {"gameId": 7, "queueName": "Ranked Solo/Duo", "links": {}, "rows": [
            {"gameName": "A", "gameTag": "1", "position": "top", "championId": 0, "me": False}]}
        first = lobby.merge_history([], lobby.history_entry(lobby_a, now=100))
        lobby_a["rows"][0]["championId"] = 86
        second = lobby.merge_history(first, lobby.history_entry(lobby_a, now=200))
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["at"], 100)
        self.assertEqual(second[0]["players"][0]["championId"], 86)


if __name__ == "__main__":
    unittest.main()
