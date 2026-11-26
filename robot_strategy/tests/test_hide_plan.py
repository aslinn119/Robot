import json
import random
import unittest

from robot_strategy.hide_plan import make_plan, suggest_answer


class HidePlanTest(unittest.TestCase):
    def test_every_plan_on_repeated_question(self):
        for lie_turn in [None] + list(range(8)):
            plan = {"game_id": "g", "lie_turn": lie_turn}
            for turn in range(1, 8):
                for kind, number, truth in [("eq", 7, True), ("gt", 7, False),
                                            ("lt", 8, True)]:
                    args = ("g", turn, 7, kind, number)
                    answer = suggest_answer(plan, *args)
                    self.assertEqual(answer["answer"], truth != (turn == lie_turn))
                    self.assertEqual(answer["uses_lie"], turn == lie_turn)
                    self.assertEqual(suggest_answer(json.loads(json.dumps(plan)), *args), answer)

    def test_seed_replay_and_used_lie(self):
        turns = set()
        for seed in range(128):
            plan = make_plan("g", decision_seed=seed)
            self.assertEqual(plan, make_plan("g", decision_seed=seed))
            turns.add(plan["lie_turn"])
            if plan["lie_turn"]:
                answer = suggest_answer(plan, "g", plan["lie_turn"], 3, "eq", 3, lie_used=True)
                self.assertEqual(answer, {"answer": True, "uses_lie": False})
        self.assertEqual(turns, set(range(8)))

    def test_start_and_invalid_requests(self):
        plan = make_plan("g", rng=random.Random(42))
        self.assertIn(plan["lie_turn"], range(1, 8))
        self.assertEqual(make_plan("g", all_truthful=True)["lie_turn"], 0)
        for game, turn, kind in [("old", 1, "eq"), ("g", 0, "eq"),
                                 ("g", 8, "eq"), ("g", True, "eq"), ("g", 1, "submit")]:
            with self.assertRaises(ValueError):
                suggest_answer(plan, game, turn, 7, kind, 7)
