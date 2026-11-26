"""Call D's official protocol adapter, without replacing its decision policy."""
from vendor_d.team_strategy import decide as team_decide, replay_profile

class StrategyUnavailable(ValueError):
    pass

def decide(payload, game_id='00000000000000000000000000000000', finished_games=(), profile=None):
    # finished_games contain public snapshots only. The client freezes this at game start.
    openings, style = replay_profile(finished_games) if profile is None else profile
    try:
        return team_decide(game_id, payload, previous_openings=openings, style=style)
    except ValueError as error:
        raise StrategyUnavailable(str(error)) from error
