import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import parasite_hub, parasite_hub_server as server
from launcher import parasite_icon

ICONS = [
    {"id": 29, "title": "Garen Icon", "yearReleased": 2010},
    {"id": 6000, "title": " Arcane Jinx ", "yearReleased": 2024},
    {"id": 29, "title": "duplicate"},
    {"id": True, "title": "bool"},
    {"id": -1, "title": "negative"},
    {"id": 7, "title": None},
    "junk",
]


class IconTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        p = patch.object(parasite_icon, "_choice_path", return_value=self.folder / parasite_icon.CHOICE_FILE)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(parasite_icon, "icons", return_value=parasite_icon.clean_icons(ICONS))
        p.start()
        self.addCleanup(p.stop)

    def test_icons_newest_first_without_junk(self):
        icons = parasite_icon.clean_icons(ICONS)
        self.assertEqual([i["id"] for i in icons], [6000, 29, 7])
        self.assertEqual(icons[0], {"id": 6000, "title": "Arcane Jinx", "year": 2024})
        self.assertEqual(icons[2]["title"], "Simge #7")
        self.assertEqual(parasite_icon.clean_icons({"no": "list"}), [])

    def test_choice_is_kept_and_reset(self):
        self.assertEqual(parasite_icon.chosen(), 0)
        self.assertEqual(parasite_icon.choose(6000), "Profil simgesi: Arcane Jinx")
        self.assertEqual(parasite_icon.chosen(), 6000)
        self.assertEqual(parasite_icon.bridge_reply(), {"type": "parasite-profile-icon", "iconId": 6000, "others": []})
        self.assertEqual(parasite_icon.listing()["icon"]["title"], "Arcane Jinx")
        self.assertEqual(parasite_icon.choose(0), "Kendi simgene dönüldü")
        self.assertEqual(parasite_icon.chosen(), 0)
        self.assertFalse((self.folder / parasite_icon.CHOICE_FILE).exists())

    def test_bad_choices_change_nothing(self):
        parasite_icon.choose(29)
        for bad in ("x", None, -5):
            self.assertEqual(parasite_icon.choose(bad), "")
        self.assertEqual(parasite_icon.chosen(), 29)
        (self.folder / parasite_icon.CHOICE_FILE).write_text("{broken", encoding="utf-8")
        self.assertEqual(parasite_icon.chosen(), 0)
        (self.folder / parasite_icon.CHOICE_FILE).write_text(json.dumps({"iconId": "29"}), encoding="utf-8")
        self.assertEqual(parasite_icon.chosen(), 0)

    def test_unknown_icon_still_chosen_by_number(self):
        self.assertEqual(parasite_icon.choose(123456), "Profil simgesi: Simge #123456")
        self.assertIsNone(parasite_icon.listing()["icon"])

    def test_hub_action_and_page(self):
        self.assertEqual(parasite_hub.ACTIONS["profile_icon"]({"iconId": 29}), "Profil simgesi: Garen Icon")
        self.assertEqual(parasite_icon.chosen(), 29)
        assert server.start()
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", server._port, timeout=5)
        conn.request("GET", "/api/icon", headers={"Host": f"127.0.0.1:{server._port}", "X-Parasite-Hub": server._token})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(data["chosen"], 29)
        self.assertEqual(len(data["icons"]), 3)


class TokenTests(unittest.TestCase):
    def test_clear_tokens_needs_the_client(self):
        with patch("launcher.parasite_offline._lcu_credentials", return_value=None):
            self.assertIn("LoL açık olmalı", parasite_icon.clear_tokens())

    def test_clear_tokens_posts_an_empty_list(self):
        with patch("launcher.parasite_offline._lcu_credentials", return_value=(1234, "t")), \
                patch("launcher.parasite_profile._lcu", return_value={}) as lcu:
            self.assertEqual(parasite_hub.ACTIONS["clear_tokens"]({}), "Tokenler kaldırıldı")
        lcu.assert_called_once_with("POST", parasite_icon.TOKENS_PATH, {"challengeIds": []})
        with patch("launcher.parasite_offline._lcu_credentials", return_value=(1234, "t")), \
                patch("launcher.parasite_profile._lcu", return_value=None):
            self.assertIn("tekrar dene", parasite_icon.clear_tokens())
