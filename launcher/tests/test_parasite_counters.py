import unittest

from launcher import parasite_counters as counters


def _stats(**records):
    """records: role -> {champion: (wins, games)}"""
    return {"patch": "16_21", "matchups": "1.5.0", "records": {r: records.get(r, {}) for r in counters.ROLES}}


class ParseTests(unittest.TestCase):
    def test_ranking(self):
        records, games = counters.parse_ranking([{"top": [["86", [], 520, 1000]], "mid": [["103", [], 490, 1000]]},
                                                 {}, "x", 250000])
        self.assertEqual(records["top"][86], (520.0, 1000.0))
        self.assertEqual(records["middle"][103], (490.0, 1000.0))
        self.assertEqual(games, 250000)

    def test_ugg_rows_are_the_opponents_side(self):
        value = {"12": {"14": {"4": [[[122, 60, 100, 50, 300, 0, 4, 0, 0, 20]]]}}}
        rows = counters.parse_ugg_matchups(value)["top"]
        self.assertEqual(rows[122], {"wins": 60.0, "games": 100.0, "gold": 300.0, "cs": 4.0, "kills": 20.0})

    def test_lolalytics_is_turned_to_the_opponents_side(self):
        rows = counters.parse_lolalytics({"counters": [{"cid": 122, "vsWr": 45, "n": 200, "d2": -3.5}]})
        self.assertAlmostEqual(rows[122]["wins"], 110.0)
        self.assertEqual(rows[122]["delta"], 3.5)

    def test_bad_data_is_skipped(self):
        self.assertEqual(counters.parse_ugg_matchups(None), {})
        self.assertEqual(counters.parse_lolalytics({"counters": [{"cid": "x"}]}), {})

    def test_patch_names(self):
        self.assertEqual(counters.display_patch("16_21"), "26.21")
        self.assertEqual(counters.display_patch("14_3"), "14.3")


class BoardTests(unittest.TestCase):
    def test_roles_are_guessed_without_sharing_one(self):
        stats = _stats(jungle={64: (500, 1000)}, top={86: (500, 1000)})
        roles = counters.assign_roles([{"id": 64, "role": None}, {"id": 86, "role": None}, {"id": 1, "role": "top"}], stats)
        self.assertEqual(roles[0], "jungle")
        self.assertEqual(roles[2], "top")
        self.assertNotEqual(roles[1], "top")
        self.assertEqual(len(set(roles)), 3)

    def test_counters_both_sites_back_rank_first(self):
        stats = _stats(top={86: (500, 1000), 1: (500, 1000), 2: (500, 1000)})
        ugg = {1: {"wins": 600, "games": 1000, "gold": 300000, "cs": 5000, "kills": 100},
               2: {"wins": 620, "games": 1000, "gold": 0, "cs": 0, "kills": 0}}
        lola = {1: {"wins": 600, "games": 1000, "delta": 9.0}}
        names = {1: {"name": "One", "slug": "one"}, 2: {"name": "Two", "slug": "two"}}
        out = counters.counters_for(86, "top", stats, ugg, lola, names)
        self.assertEqual([c["id"] for c in out], [1, 2])
        self.assertEqual(out[0]["gold15"], 300)
        self.assertEqual(out[0]["sites"], 2)

    def test_few_games_are_left_out(self):
        stats = _stats(top={86: (500, 100000)})
        ugg = {1: {"wins": 9, "games": 10, "gold": 0, "cs": 0, "kills": 0}}
        self.assertEqual(counters.counters_for(86, "top", stats, ugg, None, {}), [])

    def test_links(self):
        self.assertEqual(counters.links("wukong", "utility")["laddereye"],
                         "https://laddereye.com/champions/monkeyking?position=UTILITY")
        self.assertEqual(counters.links("leesin", "bottom")["log"],
                         "https://www.leagueofgraphs.com/champions/counters/leesin/adc/master/sr-ranked")
        self.assertEqual(counters.slug("MonkeyKing"), "wukong")

    def test_picks_take_shown_champions_and_lanes(self):
        enemies, allies = counters.picks({"theirTeam": [{"championId": 86, "assignedPosition": ""}, {"championId": 0}],
                                          "myTeam": [{"championId": 1, "assignedPosition": "TOP"}]})
        self.assertEqual(enemies, [{"id": 86, "role": None}])
        self.assertEqual(allies, [{"id": 1, "role": "top"}])


if __name__ == "__main__":
    unittest.main()
