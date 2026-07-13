"""Unit tests for the pure settlement math (mastery_awards).

Run from the repo root: ``pytest maki/cogs/legion/tests/``
"""

from maki.cogs.legion.constants import (
    MASTERY_PTS_JOIN,
    MASTERY_PTS_SURVIVED,
    MASTERY_PTS_TOP_DAMAGE,
    MASTERY_PTS_TOP_TANK,
    MASTERY_PTS_WIN,
)
from maki.cogs.legion.model.model import Player
from maki.cogs.legion.settlement import ParticipantResult, mastery_awards


def result(pid, dealt=0, taken=0, died=False) -> ParticipantResult:
    return ParticipantResult(
        player=Player(id=pid, discord_id=pid, username=f"p{pid}"),
        damage_dealt=dealt,
        damage_taken=taken,
        died=died,
    )


def test_win_survive_and_competitive_awards():
    results = [
        result(1, dealt=100, taken=10),  # top damage
        result(2, dealt=50, taken=90),  # top tank
        result(3, dealt=10, taken=20, died=True),  # died
    ]
    pts, top_damage, top_tank = mastery_awards(results, won=True)
    base = MASTERY_PTS_JOIN + MASTERY_PTS_WIN
    assert pts[1] == base + MASTERY_PTS_SURVIVED + MASTERY_PTS_TOP_DAMAGE
    assert pts[2] == base + MASTERY_PTS_SURVIVED + MASTERY_PTS_TOP_TANK
    assert pts[3] == base  # died: no survival pts
    assert top_damage == {1} and top_tank == {2}


def test_loss_still_pays_join_and_survival():
    pts, _, _ = mastery_awards([result(1, dealt=5, taken=5)], won=False)
    assert pts[1] == (
        MASTERY_PTS_JOIN
        + MASTERY_PTS_SURVIVED
        + MASTERY_PTS_TOP_DAMAGE
        + MASTERY_PTS_TOP_TANK
    )


def test_ties_all_win_and_zero_stats_award_nobody():
    results = [result(1, dealt=40), result(2, dealt=40)]
    pts, top_damage, top_tank = mastery_awards(results, won=True)
    assert top_damage == {1, 2}  # ties all win
    assert top_tank == set()  # nobody took damage: award nobody
