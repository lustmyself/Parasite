import unittest

from launcher import parasite_hero


class RankTextTests(unittest.TestCase):
    def test_divisions_and_apex_tiers(self):
        self.assertEqual(parasite_hero._rank_text({"tier": "GOLD", "division": "II", "leaguePoints": 40}), "Altın II · 40 LP")
        self.assertEqual(parasite_hero._rank_text({"tier": "GRANDMASTER", "division": "I", "leaguePoints": 1104}),
                         "Üstatlık · 1104 LP")

    def test_unranked(self):
        self.assertEqual(parasite_hero._rank_text({}), "Derecesiz")
        self.assertEqual(parasite_hero._rank_text({"tier": "NONE"}), "Derecesiz")

    def test_refresh_without_client(self):
        from unittest import mock
        with mock.patch("launcher.parasite_offline._lcu_credentials", return_value=None):
            self.assertFalse(parasite_hero.refresh())


class CutoffTests(unittest.TestCase):
    def test_parse_keeps_fresh_servers(self):
        import time
        now = int(time.time() * 1000)
        page = (f'[{{"region":"TR1","challenger":1256,"grandmaster":784,"timeFetched":{now}}},'
                f'{{"region":"PH2","challenger":500,"grandmaster":200,"timeFetched":1738093826907}}]')
        self.assertEqual(parasite_hero.parse_cutoffs(page), {"TR1": {"challenger": 1256, "grandmaster": 784}})
        escaped = page.replace('"', '\\"')
        self.assertEqual(parasite_hero.parse_cutoffs(escaped), {"TR1": {"challenger": 1256, "grandmaster": 784}})

    def test_client_region_maps_to_server(self):
        from unittest import mock
        with mock.patch.object(parasite_hero, "_cutoffs", {"TR1": {"challenger": 1256, "grandmaster": 784}}), \
                mock.patch.object(parasite_hero, "_cutoffs_at", 1e18):
            self.assertEqual(parasite_hero.cutoffs_for("TR"), {"challenger": 1256, "grandmaster": 784, "region": "TR"})
            self.assertIsNone(parasite_hero.cutoffs_for("EUW"))


class SavedCardTests(unittest.TestCase):
    def test_a_missed_read_is_tried_again(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(parasite_hero, "_dir", return_value=Path(folder)), \
                mock.patch.object(parasite_hero, "_data", None):
            self.assertIsNone(parasite_hero.get())
            (Path(folder) / "hero.json").write_text('{"name": "Parasite"}', encoding="utf-8")
            self.assertEqual(parasite_hero.get(), {"name": "Parasite"})


class MatchHistoryTests(unittest.TestCase):
    def test_asks_for_the_clients_own_range(self):
        """Asking for 2 games made the client's own Match History show only 2."""
        from unittest import mock
        asked = []

        class Response:
            def __init__(self, data):
                self.data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self.data

        def fake_get(url, **kwargs):
            asked.append(url)
            if "current-summoner/matches" in url:
                return Response({"games": {"games": []}})
            if "current-summoner" in url:
                return Response({"gameName": "a"})
            return Response({})

        with mock.patch("launcher.parasite_offline._lcu_credentials", return_value=(1, "t")),                 mock.patch.object(parasite_hero.requests, "get", side_effect=fake_get),                 mock.patch.object(parasite_hero, "cutoffs_for", return_value=None),                 mock.patch.object(parasite_hero, "_dir", return_value=__import__("pathlib").Path(__import__("tempfile").mkdtemp())):
            parasite_hero.refresh()
        history = [u for u in asked if "matches" in u]
        self.assertEqual(len(history), 1)
        self.assertIn("begIndex=0&endIndex=19", history[0])

class QuietRestartTests(unittest.TestCase):
    def test_both_update_starts_stay_quiet_then_it_expires(self):
        import os
        import tempfile
        import time
        from pathlib import Path
        from unittest import mock
        from launcher import parasite_hub
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch("utils.core.paths.get_user_data_dir", return_value=Path(folder)), \
                mock.patch.object(parasite_hub, "window_visible", return_value=False):
            self.assertFalse(parasite_hub._take_quiet_restart())
            parasite_hub.mark_quiet_restart()
            self.assertTrue(parasite_hub._take_quiet_restart())
            self.assertTrue(parasite_hub._take_quiet_restart())
            flag = Path(folder) / parasite_hub.QUIET_FLAG
            old = time.time() - parasite_hub.QUIET_FOR_S - 5
            os.utime(flag, (old, old))
            self.assertFalse(parasite_hub._take_quiet_restart())
            self.assertFalse(flag.exists())

    def test_an_open_window_is_not_hidden(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from launcher import parasite_hub
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch("utils.core.paths.get_user_data_dir", return_value=Path(folder)), \
                mock.patch.object(parasite_hub, "window_visible", return_value=True):
            parasite_hub.mark_quiet_restart()
            self.assertFalse(parasite_hub._take_quiet_restart())


if __name__ == "__main__":
    unittest.main()
