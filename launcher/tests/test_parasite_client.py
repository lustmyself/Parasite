import json
import unittest
from types import SimpleNamespace
from unittest import mock

from launcher import parasite_client


def _state(connections):
    broadcaster = SimpleNamespace(websocket_server=SimpleNamespace(connections=connections),
                                  broadcast_raw=mock.Mock())
    return SimpleNamespace(ui_skin_thread=SimpleNamespace(broadcaster=broadcaster)), broadcaster


class OpenPanelTests(unittest.TestCase):
    def tearDown(self):
        parasite_client.attach_state(None)

    def test_league_closed(self):
        self.assertIn("League", parasite_client.open_panel(False))

    def test_client_not_connected(self):
        state, broadcaster = _state(set())
        parasite_client.attach_state(state)
        self.assertIn("bağlanılamadı", parasite_client.open_panel(True))
        broadcaster.broadcast_raw.assert_not_called()

    def test_opens_the_panel_in_the_client(self):
        state, broadcaster = _state({object()})
        parasite_client.attach_state(state)
        self.assertIn("açıldı", parasite_client.open_panel(True))
        broadcaster.broadcast_raw.assert_called_once()
        self.assertEqual(json.loads(broadcaster.broadcast_raw.call_args[0][0]), {"type": "parasite-open-hub"})


if __name__ == "__main__":
    unittest.main()
