import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from launcher import parasite_skins
from pengu.communication import parasite_custom_skins

CHAMPIONS = [
    {"id": -1, "name": "None", "alias": "None"},
    {"id": 103, "name": "Ahri", "alias": "Ahri"},
    {"id": 266, "name": "Aatrox", "alias": "Aatrox"},
    {"id": "x", "name": "Bad", "alias": "Bad"},
]


def _mod(wad: str) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr(f"WAD/{wad}.wad.client", b"wad")
    return data.getvalue()


class SkinsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        p = patch.object(parasite_custom_skins, "folder", return_value=self.folder)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(parasite_skins, "champions", return_value=parasite_skins.clean_champions(CHAMPIONS))
        p.start()
        self.addCleanup(p.stop)

    def test_champion_list_keeps_real_champions_by_name(self):
        names = [c["name"] for c in parasite_skins.clean_champions(CHAMPIONS)]
        self.assertEqual(names, ["Aatrox", "Ahri"])
        self.assertEqual(parasite_skins.clean_champions({"x": 1}), [])

    def test_listing_guesses_the_champion_from_the_wad(self):
        (self.folder / "Star Ahri.zip").write_bytes(_mod("Ahri"))
        (self.folder / "Mystery.zip").write_bytes(_mod("Common"))
        data = parasite_skins.listing()
        by_name = {s["name"]: s for s in data["skins"]}
        self.assertEqual(by_name["Star Ahri.zip"]["championId"], 103)
        self.assertEqual(by_name["Star Ahri.zip"]["champion"], "Ahri")
        self.assertIsNone(by_name["Mystery.zip"]["championId"])
        self.assertEqual([c["name"] for c in data["champions"]], ["Aatrox", "Ahri"])

    def test_toggle_needs_a_champion_and_keeps_one_per_champion(self):
        (self.folder / "a.zip").write_bytes(_mod("Common"))
        (self.folder / "b.zip").write_bytes(_mod("Common"))
        parasite_skins.listing()
        self.assertEqual(parasite_skins.toggle("a.zip", True), "Önce şampiyonu seç")
        parasite_skins.set_champion("a.zip", 266)
        parasite_skins.set_champion("b.zip", 266)
        self.assertTrue(parasite_skins.toggle("a.zip", True))
        parasite_skins.toggle("b.zip", True)
        on = {s["name"]: s["enabled"] for s in parasite_skins.listing()["skins"]}
        self.assertEqual(on, {"a.zip": False, "b.zip": True})

    def test_upload_and_delete(self):
        body = _mod("Ahri")
        self.assertEqual(parasite_skins.import_upload("bad.exe", io.BytesIO(body), len(body)),
                         "Yalnızca .zip, .fantome ve .modpkg dosyaları eklenebilir")
        self.assertEqual(parasite_skins.import_upload("../x.zip", io.BytesIO(body), len(body)), "x eklendi")
        self.assertTrue((self.folder / "x.zip").is_file())
        self.assertEqual(parasite_skins.import_upload("y.zip", io.BytesIO(body[:5]), len(body)), "Dosya yarım geldi")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["x.zip"])
        parasite_skins.listing()
        parasite_skins.toggle("x.zip", True)
        self.assertEqual(parasite_skins.delete("x.zip"), "x silindi")
        state = json.loads((self.folder / parasite_custom_skins.STATE_FILE).read_text(encoding="utf-8"))
        self.assertNotIn("x.zip", state)
        self.assertEqual(parasite_skins.delete("../secret.zip"), "")



class ChampionListCacheTests(unittest.TestCase):
    """champions() is called by hub pages polled every couple of seconds: offline it must not
    download again on every call, and callers must not all download at once."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        p = patch.object(parasite_custom_skins, "folder", return_value=self.folder)
        p.start()
        self.addCleanup(p.stop)
        p = patch.dict(parasite_skins._champions, {"at": None, "items": [], "retry": False})
        p.start()
        self.addCleanup(p.stop)
        self.clock = [1000.0]
        p = patch.object(parasite_skins.time, "monotonic", side_effect=lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)

    def test_offline_without_a_saved_list_waits_a_minute_before_trying_again(self):
        with patch.object(parasite_skins, "_download", return_value=[]) as download:
            self.assertEqual(parasite_skins.champions(), [])
            self.assertEqual(parasite_skins.champions(), [])
            self.clock[0] += 30
            parasite_skins.champions()
            self.assertEqual(download.call_count, 1)
            self.clock[0] += parasite_skins.CHAMPIONS_RETRY_S
            parasite_skins.champions()
            self.assertEqual(download.call_count, 2)

    def test_offline_uses_the_saved_list_and_retries_the_network_later(self):
        (self.folder / parasite_skins.CHAMPIONS_FILE).write_text(json.dumps(CHAMPIONS), encoding="utf-8")
        with patch.object(parasite_skins, "_download", return_value=[]) as download:
            self.assertEqual([c["name"] for c in parasite_skins.champions()], ["Aatrox", "Ahri"])
            parasite_skins.champions()
            self.assertEqual(download.call_count, 1)
        self.clock[0] += parasite_skins.CHAMPIONS_RETRY_S + 1
        fresh = parasite_skins.clean_champions(CHAMPIONS[:2])
        with patch.object(parasite_skins, "_download", return_value=fresh) as download:
            self.assertEqual(parasite_skins.champions(), fresh)
            self.clock[0] += parasite_skins.CHAMPIONS_RETRY_S * 10
            parasite_skins.champions()
            self.assertEqual(download.call_count, 1)

    def test_a_downloaded_list_is_kept_for_hours(self):
        items = parasite_skins.clean_champions(CHAMPIONS)
        with patch.object(parasite_skins, "_download", return_value=items) as download:
            parasite_skins.champions()
            self.clock[0] += parasite_skins.CHAMPIONS_TTL_S - 1
            parasite_skins.champions()
            self.assertEqual(download.call_count, 1)
            self.clock[0] += 2
            parasite_skins.champions()
            self.assertEqual(download.call_count, 2)

    def test_concurrent_callers_share_one_download(self):
        import threading
        started, release = threading.Event(), threading.Event()
        items = parasite_skins.clean_champions(CHAMPIONS)

        def slow():
            started.set()
            release.wait(5)
            return items

        results = []
        with patch.object(parasite_skins, "_download", side_effect=slow) as download:
            threads = [threading.Thread(target=lambda: results.append(parasite_skins.champions()))
                       for _ in range(4)]
            threads[0].start()
            self.assertTrue(started.wait(5))
            for t in threads[1:]:
                t.start()
            release.set()
            for t in threads:
                t.join(5)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(results, [items] * 4)

    def test_a_stale_list_is_handed_back_while_another_caller_downloads(self):
        old = parasite_skins.clean_champions(CHAMPIONS[:2])
        parasite_skins._champions.update(at=0.0, items=old, retry=True)
        parasite_skins._fetch_lock.acquire()
        try:
            with patch.object(parasite_skins, "_download") as download:
                self.assertEqual(parasite_skins.champions(), old)
                download.assert_not_called()
        finally:
            parasite_skins._fetch_lock.release()


if __name__ == "__main__":
    unittest.main()
