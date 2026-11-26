"""回归跨局偏好、保密边界及同局重试。"""
import unittest

from robot_strategy.team_strategy import decide, replay_profile


class TeamStrategyTest(unittest.TestCase):
    def test_preferences_and_rotation(self):
        for cut, expected in [(3, "edge"), (5, "balanced")]:
            games = [dict(mode="robot_hides", phase="finished",
                          history=[dict(comparison="gt", number=cut)]) for _ in range(2)]
            cuts = []
            for i in range(25):
                openings, style = replay_profile(games)
                self.assertEqual(style, expected)
                p = dict(mode="player_hides", purpose="guess_next", history=[],
                         remaining_questions=7, max_lies=1)
                args = dict(previous_openings=openings, style=style)
                result = decide(str(i), p, **args)
                self.assertEqual(result, decide(str(i), p, **args))
                cuts.append(result["number"] - (result["comparison"] == "lt"))
                games.append(dict(mode="player_hides", phase="finished", history=[result]))
            self.assertTrue(all(x != y for x, y in zip(cuts, cuts[1:])))
            for start in range(0, 25, 5):
                self.assertEqual(set(cuts[start:start+5]), set(range(3, 8)))
            self.assertEqual(abs(cuts[0]-5), 2 if expected == "edge" else 0)

    def test_private_inputs_rejected(self):
        p = dict(mode="player_hides", purpose="guess_next", history=[],
                 remaining_questions=7, max_lies=1)
        for field in ("secret", "decision_seed", "lie_used"):
            with self.assertRaisesRegex(ValueError, "STRATEGY_INVALID"):
                decide("g", dict(p, **{field: 1}))

    def test_only_finished_games_affect_preferences(self):
        self.assertEqual(replay_profile([{"phase": "waiting_answer"}]), ([], "mixed"))
