"""机器人藏牌侧的私有计划。C 保存计划并分配正式问题序号。"""
import random

from .strategy import answer_suggestion


def _check_game(game_id):
    if not isinstance(game_id, str) or not game_id.strip():
        raise ValueError("game_id must be a nonempty string")


def make_plan(game_id, *, all_truthful=False, rng=None):
    """开局调用一次。返回可随局保存的 JSON 对象。"""
    _check_game(game_id)
    if type(all_truthful) is not bool:
        raise ValueError("all_truthful must be boolean")
    source = random if rng is None else rng
    return {"game_id": game_id,
            "lie_turn": None if all_truthful else source.randint(1, 7)}


def suggest_answer(plan, game_id, question_no, secret, kind, number):
    """只为已确认的普通问题提供建议。重播由 C 读取已提交答案。"""
    _check_game(game_id)
    if not isinstance(plan, dict) or set(plan) != {"game_id", "lie_turn"}:
        raise ValueError("invalid private plan")
    if plan["game_id"] != game_id:
        raise ValueError("plan belongs to another game")
    if type(question_no) is not int or not 1 <= question_no <= 7:
        raise ValueError("question_no must be an integer from 1 to 7")
    turn = plan["lie_turn"]
    if turn is not None and (type(turn) is not int or not 1 <= turn <= 7):
        raise ValueError("invalid lie_turn")
    return answer_suggestion(secret, kind, number, use_lie=question_no == turn)
