"""团队 v1.0 的 strategy.decide 业务适配；网络收发及确认由调用层负责。"""
from .hide_plan import make_plan, suggest_answer
from .strategy import suggest


def replay_profile(finished_games):
    """输入同一轮连续游玩的公开快照，按结束顺序；开局时冻结结果。"""
    openings = []
    edges = []
    for game in finished_games:
        if game["phase"] != "finished" or not game["history"]:
            continue
        first = game["history"][0]
        comparison = first["comparison"]
        number = first["number"]
        if game["mode"] == "player_hides":
            openings.append(dict(kind=comparison, number=number))
        elif game["mode"] == "robot_hides" and comparison in ("gt", "lt"):
            # 玩家自己选过的切分越靠近中点，下一局越倾向平分开场。
            cut = number if comparison == "gt" else number - 1
            edges.append(abs(cut - 5) >= 2)
    recent = edges[-3:]
    style = "mixed"
    if len(recent) >= 2:
        if sum(recent) * 2 > len(recent):
            style = "edge"
        elif sum(recent) * 2 < len(recent):
            style = "balanced"
    return openings, style


def decide(game_id, payload, *, previous_openings=(), style="mixed"):
    purpose = payload["purpose"]
    if type(payload["max_lies"]) is not int or payload["max_lies"] != 1:
        raise ValueError("STRATEGY_INVALID")
    result = dict(comparison=None, number=None, answer=None, lie_applied=None,
                  candidates=[], certainty="not_final")
    if purpose == "guess_next" and payload["mode"] == "player_hides":
        if set(payload) != {"purpose", "mode", "history", "remaining_questions", "max_lies"}:
            raise ValueError("STRATEGY_INVALID")
        history = []
        for row in payload["history"]:
            if set(row) != {"question_id", "comparison", "number", "answer"}:
                raise ValueError("STRATEGY_INVALID")
            history.append(dict(kind=row["comparison"], number=row["number"], answer=row["answer"]))
        choice = suggest(history, payload["remaining_questions"], game_id=game_id,
                         previous_openings=previous_openings, style=style)
        result["candidates"] = sorted(choice["s0"] + choice["s1"])
        if choice["status"] == "inconsistent":
            raise ValueError("NO_CONSISTENT_CANDIDATE")
        if choice["status"] == "insufficient":
            if payload["remaining_questions"] != 0:
                raise ValueError("STRATEGY_INVALID")
            return dict(result, decision="final_submit", number=result["candidates"][0], certainty="guess")
        proposal = choice["proposal"]
        if choice["status"] == "certain":
            return dict(result, decision="final_submit", number=proposal["number"], certainty="unique")
        return dict(result, decision="question", comparison=proposal["kind"], number=proposal["number"])
    if purpose == "answer_question" and payload["mode"] == "robot_hides":
        if type(payload["decision_seed"]) is not int:
            raise ValueError("STRATEGY_INVALID")
        plan = make_plan(game_id, decision_seed=payload["decision_seed"])
        q = payload["question"]
        answer = suggest_answer(plan, game_id, payload["question_ordinal"], payload["secret"],
                                q["comparison"], q["number"], lie_used=payload["lie_used"])
        return dict(result, decision="answer", answer=answer["answer"], lie_applied=answer["uses_lie"])
    raise ValueError("STRATEGY_INVALID")
