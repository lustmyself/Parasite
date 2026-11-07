import unittest
from unittest import mock

from launcher import parasite_auto


def _session(kind, me=1, completed=None, bans=(), team=()):
    actions = [[{"id": 7, "actorCellId": me, "type": kind, "isInProgress": True, "completed": False, "championId": 0}]]
    for cell, champion in completed or []:
        actions.insert(0, [{"id": 100 + cell, "actorCellId": cell, "type": "pick", "completed": True,
                            "championId": champion}])
    return {"localPlayerCellId": me, "actions": actions, "bans": {"myTeamBans": list(bans), "theirTeamBans": []},
            "myTeam": [{"cellId": cell, "championPickIntent": intent, "championId": 0} for cell, intent in team]}


ON = {"accept": True, "ban": True, "pick": True, "bans": [238, 157], "picks": [103, 99]}


class CleanTests(unittest.TestCase):
    def test_bad_values_fall_back(self):
        self.assertEqual(parasite_auto.clean(None), parasite_auto.DEFAULTS)
        self.assertEqual(parasite_auto.clean({"accept": "yes", "bans": "x"}), parasite_auto.DEFAULTS)

    def test_lists_keep_unique_positive_ids_up_to_the_max(self):
        out = parasite_auto.clean({"picks": [1, 1, -2, True, "3", 4, 5, 6, 7, 8]})
        self.assertEqual(out["picks"], [1, 4, 5, 6, 7])


class ChooseTests(unittest.TestCase):
    def test_pick_takes_the_first_free_champion(self):
        session = _session("pick", completed=[(6, 103)])
        self.assertEqual(parasite_auto.choose(session, ON), (7, 99, "pick"))

    def test_ban_skips_what_a_teammate_wants(self):
        session = _session("ban", team=[(2, 238)])
        self.assertEqual(parasite_auto.choose(session, ON), (7, 157, "ban"))

    def test_ban_skips_banned_champions(self):
        session = _session("ban", bans=[238])
        self.assertEqual(parasite_auto.choose(session, ON), (7, 157, "ban"))

    def test_only_what_the_client_allows(self):
        session = _session("pick")
        self.assertEqual(parasite_auto.choose(session, ON, pickable={99}), (7, 99, "pick"))
        # A list from the client that leaves out every choice is not trusted
        self.assertEqual(parasite_auto.choose(session, ON, pickable={1}), (7, 103, "pick"))

    def test_switched_off_does_nothing(self):
        self.assertIsNone(parasite_auto.choose(_session("pick"), dict(ON, pick=False)))

    def test_someone_elses_turn(self):
        self.assertIsNone(parasite_auto.choose(_session("pick", me=1) | {"localPlayerCellId": 3}, ON))

    def test_no_session(self):
        self.assertIsNone(parasite_auto.choose(None, ON))

    def test_without_the_in_progress_flag_the_open_group_is_current(self):
        session = _session("pick")
        for group in session["actions"]:
            for action in group:
                action.pop("isInProgress", None)
        self.assertEqual(parasite_auto.choose(session, ON), (7, 103, "pick"))

    def test_an_empty_allowed_list_does_not_block(self):
        session = _session("ban")
        self.assertEqual(parasite_auto.choose(session, ON, bannable=None), (7, 238, "ban"))


class LockInTests(unittest.TestCase):
    def setUp(self):
        parasite_auto._done.clear()

    def _run(self, session, times):
        calls = []

        def lcu(method, path, body=None):
            calls.append((method, path, body))
            return session if path.endswith("/session") else {}
        with mock.patch.object(parasite_auto, "_lcu", side_effect=lcu):
            for _ in range(times):
                parasite_auto._champ_select(dict(ON))
        return [c for c in calls if c[0] != "GET"]

    def test_hover_then_lock_in(self):
        sent = self._run(_session("ban"), 1)
        self.assertEqual(sent, [("PATCH", "/lol-champ-select/v1/session/actions/7", {"championId": 238}),
                                ("POST", "/lol-champ-select/v1/session/actions/7/complete", None)])

    def test_an_action_left_open_is_tried_again_both_ways(self):
        sent = self._run(_session("ban"), parasite_auto.MAX_TRIES + 3)
        posts = [c for c in sent if c[0] == "POST"]
        one_call = [c for c in sent if c[2] == {"championId": 238, "completed": True}]
        self.assertEqual(len(posts) + len(one_call), parasite_auto.MAX_TRIES)
        self.assertEqual(sent[2], ("PATCH", "/lol-champ-select/v1/session/actions/7",
                                   {"championId": 238, "completed": True}))

    def test_planning_phase_waits_and_keeps_the_tries(self):
        planning = dict(_session("ban"), timer={"phase": "PLANNING"})
        self.assertEqual(self._run(planning, 10), [])
        sent = self._run(dict(_session("ban"), timer={"phase": "BAN_PICK"}), 1)
        self.assertEqual(len(sent), 2)


def _game(game_id=42, queue=420, custom=False, kind="RANKED_SOLO_5x5"):
    return {"gameData": {"gameId": game_id, "isCustomGame": custom, "queue": {"id": queue, "type": kind}}}


class RequeueTests(unittest.TestCase):
    def setUp(self):
        parasite_auto._requeue.update(game=None, until=0.0, not_before=0.0)

    def _run(self, phases, session=None, lobby=None, search_ok=True):
        calls = []

        def lcu(method, path, body=None):
            calls.append((method, path))
            if path == "/lol-gameflow/v1/session":
                return session if session is not None else _game()
            if path == "/lol-lobby/v2/lobby":
                return lobby if lobby is not None else {"canStartActivity": True, "localMember": {"isLeader": True}}
            if path.endswith("/search") and not search_ok:
                return None
            return {}
        with mock.patch.object(parasite_auto, "_lcu", side_effect=lcu):
            for phase in phases:
                parasite_auto._after_game(phase)
        return [c for c in calls if c[0] != "GET"]

    def test_matchmade_game_goes_back_and_queues(self):
        sent = self._run(["InProgress", "PreEndOfGame", "EndOfGame", "EndOfGame", "Lobby", "Matchmaking"])
        self.assertEqual(sent, [("POST", "/lol-lobby/v2/play-again"),
                                ("POST", "/lol-lobby/v2/lobby/matchmaking/search")])

    def test_custom_games_and_practice_tool_are_left_alone(self):
        self.assertEqual(self._run(["EndOfGame", "Lobby"], session=_game(custom=True, queue=-1)), [])
        self.assertEqual(self._run(["EndOfGame", "Lobby"], session=_game(queue=3140, kind="PRACTICETOOL")), [])

    def test_a_lobby_without_a_game_before_is_not_queued(self):
        self.assertEqual(self._run(["Lobby", "Lobby"]), [])

    def test_party_member_leaves_the_queue_to_the_leader(self):
        sent = self._run(["EndOfGame", "Lobby", "Lobby"], lobby={"localMember": {"isLeader": False}})
        self.assertEqual(sent, [("POST", "/lol-lobby/v2/play-again")])

    def test_waits_while_the_lobby_cannot_start(self):
        sent = self._run(["EndOfGame", "Lobby", "Lobby"], lobby={"canStartActivity": False, "localMember": {"isLeader": True}})
        self.assertEqual(sent, [("POST", "/lol-lobby/v2/play-again")])

    def test_a_failed_search_is_tried_again(self):
        sent = self._run(["EndOfGame", "Lobby", "Lobby"], search_ok=False)
        self.assertEqual(sent.count(("POST", "/lol-lobby/v2/lobby/matchmaking/search")), 2)

    def test_requeue_alone_keeps_the_thread(self):
        self.assertTrue(parasite_auto._any_on(parasite_auto.clean({"requeue": True})))
        self.assertFalse(parasite_auto._any_on(parasite_auto.clean({})))


class LastSecondTests(unittest.TestCase):
    def setUp(self):
        parasite_auto._done.clear()
        parasite_auto._hovered.clear()
        parasite_auto._dodge.update(armed=False, state="")

    def _run(self, session, config):
        calls = []

        def lcu(method, path, body=None):
            calls.append((method, path, body))
            return session if path.endswith("/session") else {}
        with mock.patch.object(parasite_auto, "_lcu", side_effect=lcu):
            delay = parasite_auto._champ_select(config)
        return [c for c in calls if c[0] != "GET"], delay

    def test_the_settings_keep_known_choices_only(self):
        out = parasite_auto.clean({"ban_at": 3, "pick_at": 7, "requeue_delay": 30, "requeue_dodge": True})
        self.assertEqual((out["ban_at"], out["pick_at"], out["requeue_delay"], out["requeue_dodge"]), (3, 0, 30, True))
        self.assertEqual(parasite_auto.clean({"ban_at": True})["ban_at"], 0)

    def test_waits_for_the_last_seconds_and_hovers_meanwhile(self):
        session = dict(_session("pick"), timer={"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 20000})
        sent, delay = self._run(session, dict(ON, pick_at=3))
        self.assertEqual(sent, [("PATCH", "/lol-champ-select/v1/session/actions/7", {"championId": 103})])
        self.assertEqual(delay, parasite_auto.BUSY_S)
        # Hovered once only
        sent, _ = self._run(session, dict(ON, pick_at=3))
        self.assertEqual(sent, [])

    def test_locks_in_once_the_time_has_come(self):
        session = dict(_session("pick"), timer={"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 2900})
        sent, _ = self._run(session, dict(ON, pick_at=3))
        self.assertIn(("POST", "/lol-champ-select/v1/session/actions/7/complete", None), sent)

    def test_the_last_second_is_never_later_than_1_2s(self):
        timer = {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 1500}
        self.assertGreater(parasite_auto._wait_ms(dict(ON, ban_at=1), "ban", timer), 0)
        timer["adjustedTimeLeftInPhase"] = 1100
        self.assertEqual(parasite_auto._wait_ms(dict(ON, ban_at=1), "ban", timer), 0)
        self.assertEqual(parasite_auto._wait_ms(dict(ON, ban_at=0), "ban", {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 9000}), 0)

    def test_an_armed_dodge_goes_at_the_end_of_champ_select(self):
        parasite_auto._dodge["armed"] = True
        early = {"phase": "FINALIZATION", "adjustedTimeLeftInPhase": 9000}
        sent, delay = self._run(dict(_session("pick"), timer=early), dict(ON, ban=False, pick=False))
        self.assertEqual(sent, [])
        self.assertEqual(delay, parasite_auto.FAST_S)
        late = {"phase": "FINALIZATION", "adjustedTimeLeftInPhase": 1000}
        sent, _ = self._run(dict(_session("pick"), timer=late), dict(ON, ban=False, pick=False))
        self.assertEqual(sent, [("POST", parasite_auto.DODGE_PATH, {})])
        self.assertFalse(parasite_auto._dodge["armed"])

    def test_back_in_the_lobby_from_champ_select_is_a_dodge(self):
        self.assertTrue(parasite_auto.after_dodge("ChampSelect", "Lobby"))
        self.assertFalse(parasite_auto.after_dodge("ChampSelect", "InProgress"))
        self.assertFalse(parasite_auto.after_dodge("Matchmaking", "Lobby"))


if __name__ == "__main__":
    unittest.main()
