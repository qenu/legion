"""Unit tests for the pure game math in calculator.py.

Run from the repo root: ``pytest maki/cogs/legion/tests/``
"""

import random

import pytest

from maki.cogs.legion.calculator import (
    CombatantStats,
    apply_mastery_drain,
    apply_mastery_gain,
    craft_double_chance,
    drainable_exp,
    eval_formula,
    gather_payout_chunks,
    get_mob_stats,
    mastery_erosion_pts,
    mastery_level_cost,
    quality_from_mutations,
    roll_mutations,
    tier_multiplier,
)
from maki.cogs.legion.constants import (
    CRAFT_DOUBLE_CHANCE_PER_LEVEL,
    MASTERY_EROSION_GRACE_HOURS,
    MASTERY_EROSION_PER_DAY,
    MASTERY_EXP_BASE,
    MASTERY_HARD_CAP,
    MASTERY_SOFT_CAP,
    MUTATION_MAX,
    MUTATION_MIN,
    WeaponQuality,
)


# --- eval_formula -----------------------------------------------------------


def _stats():
    player = CombatantStats(
        attack=50, defense=20, speed=10, health=30, max_health=100, taunt=3
    )
    target = CombatantStats(
        attack=5, defense=5, speed=5, health=200, max_health=1000, taunt=0
    )
    return {
        "atk": 50,
        "attack": 50,
        "def": 20,
        "defense": 20,
        "speed": 10,
        "hp": 30,
        "max_hp": 100,
        "player": player,
        "target": target,
    }


def test_plain_numbers_pass_through():
    assert eval_formula(20) == 20
    assert eval_formula(19.6) == 20
    assert eval_formula("20") == 20


def test_legacy_flat_vars():
    assert eval_formula("{atk} + 6", _stats()) == 56
    assert eval_formula("{def}*15%", _stats()) == 3
    assert eval_formula("{atk}*10% + 20", _stats()) == 25


def test_player_namespace():
    assert eval_formula("{player.attack}*20% + 5", _stats()) == 15
    assert eval_formula("{player.defense}+20", _stats()) == 40


def test_shield_key():
    stats = _stats()
    stats["player"].shield = 40
    assert eval_formula("{player.shield}*50%", stats) == 20
    assert eval_formula("{target.shield}", stats) == 0


def test_target_namespace():
    assert eval_formula("{target.health}*3%", _stats()) == 6
    assert eval_formula("{target.max_health}*2%", _stats()) == 20
    # missing_health is derived: max_health - health = 800
    assert eval_formula("{target.missing_health}*5%", _stats()) == 40


def test_unknown_variable_raises():
    with pytest.raises(ValueError):
        eval_formula("{nonsense}", _stats())
    with pytest.raises(ValueError):
        eval_formula("{player.nonsense}", _stats())
    with pytest.raises(ValueError):
        eval_formula("{player.__class__}", _stats())


def test_missing_namespace_raises():
    # A passive validated without a target must reject {target.*}.
    stats = _stats()
    del stats["target"]
    with pytest.raises(ValueError):
        eval_formula("{target.health}*3%", stats)


def test_disallowed_syntax_raises():
    with pytest.raises(ValueError):
        eval_formula("__import__('os')", {})
    with pytest.raises(ValueError):
        eval_formula("(1).__class__", {})


# --- mob scaling --------------------------------------------------------------


class _FakeMob:
    base_hp = 100
    base_atk = 10
    base_def = 5
    base_speed = 6


def test_party_size_scales_hp_hard_but_atk_gently():
    solo = get_mob_stats(_FakeMob, 3, 1)
    five = get_mob_stats(_FakeMob, 3, 5)
    assert five["hp"] > solo["hp"] * 1.5  # HP scales hard
    # atk uses the LOW modifier: 5 players may only add ~20%, never double
    assert five["atk"] <= solo["atk"] * 1.25


# --- mastery math ---------------------------------------------------------


def test_gain_levels_up_and_hard_cap_discards():
    level, exp, gained = apply_mastery_gain(0, 0, mastery_level_cost(1))
    assert (level, exp, gained) == (1, 0, 1)
    # hard cap: overflow exp is discarded, exp pinned to 0
    level, exp, gained = apply_mastery_gain(MASTERY_HARD_CAP - 1, 0, 10**9)
    assert (level, exp) == (MASTERY_HARD_CAP, 0)
    level, exp, gained = apply_mastery_gain(MASTERY_HARD_CAP, 0, 50)
    assert (level, exp, gained) == (MASTERY_HARD_CAP, 0, 0)


def test_drain_never_breaches_soft_cap_floor():
    # at the floor: nothing to drain
    assert drainable_exp(MASTERY_SOFT_CAP, 0) == 0
    level, exp, drained, lost = apply_mastery_drain(MASTERY_SOFT_CAP, 0, 999)
    assert (level, exp, drained, lost) == (MASTERY_SOFT_CAP, 0, 0, 0)
    # one level above the floor: drain eats exp then the level, stops at floor
    above = mastery_level_cost(MASTERY_SOFT_CAP + 1)
    level, exp, drained, lost = apply_mastery_drain(MASTERY_SOFT_CAP + 1, 5, 10**6)
    assert (level, exp) == (MASTERY_SOFT_CAP, 0)
    assert drained == above + 5
    assert lost == 1


def test_erosion_grace_window():
    grace = MASTERY_EROSION_GRACE_HOURS * 3600
    assert mastery_erosion_pts(grace - 1) == 0
    assert mastery_erosion_pts(grace + 86400) == MASTERY_EROSION_PER_DAY


# --- craft ------------------------------------------------------------------


def test_craft_double_chance_linear_and_clamped():
    assert craft_double_chance(0) == 0
    assert craft_double_chance(-3) == 0
    assert craft_double_chance(4) == pytest.approx(4 * CRAFT_DOUBLE_CHANCE_PER_LEVEL)
    assert craft_double_chance(10**6) == 1.0


def test_quality_tiers():
    assert quality_from_mutations({}) == WeaponQuality.STANDARD
    assert quality_from_mutations({"1": 125, "2": 125}) == WeaponQuality.MASTERWORK
    assert quality_from_mutations({"1": 104}) == WeaponQuality.FINE
    assert quality_from_mutations({"1": 100}) == WeaponQuality.STANDARD
    assert quality_from_mutations({"1": 75}) == WeaponQuality.CRUDE


def test_roll_mutations_range_and_keys():
    rng = random.Random(42)
    muts = roll_mutations([7, 8], legion_level=0, rng=rng)
    assert set(muts) == {"7", "8"}  # stringified for JSON round-trips
    assert all(MUTATION_MIN <= v <= MUTATION_MAX for v in muts.values())


def test_tier_multiplier_clamps():
    assert tier_multiplier(0) == 100
    assert tier_multiplier(1) == 100
    assert tier_multiplier(5) == 150
    assert tier_multiplier(99) == 150


# --- gathering -----------------------------------------------------------------


def test_gather_payout_capped_by_bag():
    # level 0 bag = 4h: 12 chunks of 20min, 4 mastery pts -- even for a week AFK
    chunks, pts = gather_payout_chunks(7 * 24 * 60, gather_level=0)
    assert (chunks, pts) == (12, 4)
    # short session: partial chunks floor away
    chunks, pts = gather_payout_chunks(59, gather_level=0)
    assert (chunks, pts) == (2, 0)
