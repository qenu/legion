"""Pure game math for the legion cog -- no DB access, fully unit-testable."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from maki.cogs.legion.constants import (
    GATHER_BAG_BASE_HOURS,
    SKILL_TIER_MAX,
    SKILL_TIER_MULTIPLIERS,
    SkillTier,
    GATHER_BAG_HOURS_PER_LEVEL,
    GATHER_CHUNK_MINUTES,
    GATHER_MASTERY_MAX_PER_AFK,
    LEGION_EXP_BASE,
    LEGION_UPGRADE_QTY_PER_MEMBER,
    MASTERY_EROSION_GRACE_HOURS,
    MASTERY_EROSION_PER_DAY,
    MASTERY_EXP_BASE,
    MASTERY_HARD_CAP,
    MASTERY_SOFT_CAP,
    MUTATION_LEGION_SHIFT,
    MUTATION_LEGION_SHIFT_CAP,
    MUTATION_MAX,
    MUTATION_MIN,
    QUALITY_TIER_THRESHOLDS,
    WeaponQuality,
)

if TYPE_CHECKING:
    # Type hints only -- a runtime import here would be circular
    # (model/__init__ -> repository -> calculator).
    from maki.cogs.legion.model.model import Mob, MobDrop


def get_hp_bonus(level: int) -> int:
    return level * 10


def get_shield_bonus(level: int) -> int:
    return level * 5


def get_def_bonus(level: int) -> int:
    return level * 3


def get_regen_rate(level: int) -> int:
    return int(level * 0.1)  # HP per minute


def get_mob_stats(mob: Mob, danger: int, player_count: int) -> dict:
    """Mob stats scale off the hunting ground's DANGER rating + party size.
    Legion level never scales mobs -- it only unlocks grounds (no treadmill)."""
    danger_modifier = 1 + (danger * 0.1)
    player_modifier = 1 + (player_count * 0.2)
    player_modifier_low = 1 + (player_count * 0.05)

    return {
        "hp": int(mob.base_hp * danger_modifier * player_modifier),
        "atk": int(mob.base_atk * danger_modifier * player_modifier),
        "def": int(mob.base_def * danger_modifier * player_modifier_low),
        "speed": int(mob.base_speed * danger_modifier * player_modifier_low),
    }


# --- Mastery math ---------------------------------------------------------
# Storage convention: `exp` is progress *within* the current level.


def mastery_level_cost(level: int) -> int:
    """Exp required to advance from ``level - 1`` to ``level``."""
    return level * MASTERY_EXP_BASE


def drainable_exp(level: int, exp: int) -> int:
    """Exp sitting above the soft-cap floor (level MASTERY_SOFT_CAP, 0 exp).

    This is the maximum the zero-sum drain can ever take from a mastery.
    """
    if level < MASTERY_SOFT_CAP:
        return 0
    above = sum(mastery_level_cost(lv) for lv in range(MASTERY_SOFT_CAP + 1, level + 1))
    return above + exp


def apply_mastery_gain(level: int, exp: int, pts: int) -> tuple[int, int, int]:
    """Add ``pts`` exp. Returns ``(new_level, new_exp, levels_gained)``.

    Exp past the hard cap is discarded (a hard-capped mastery holds 0 exp).
    """
    if level >= MASTERY_HARD_CAP:
        return level, 0, 0
    gained = 0
    exp += pts
    while level < MASTERY_HARD_CAP and exp >= mastery_level_cost(level + 1):
        exp -= mastery_level_cost(level + 1)
        level += 1
        gained += 1
    if level >= MASTERY_HARD_CAP:
        exp = 0
    return level, exp, gained


def mastery_erosion_pts(inactive_seconds: float) -> int:
    """Exp to erode from each above-soft-cap mastery after a stretch of
    inactivity: nothing within the grace window, then MASTERY_EROSION_PER_DAY
    per day beyond it. Pure/lazy -- the caller passes elapsed seconds."""
    grace = MASTERY_EROSION_GRACE_HOURS * 3600
    if inactive_seconds <= grace:
        return 0
    days = (inactive_seconds - grace) / 86400
    return int(days * MASTERY_EROSION_PER_DAY)


def apply_mastery_drain(level: int, exp: int, pts: int) -> tuple[int, int, int, int]:
    """Remove up to ``pts`` exp, never dropping below the soft-cap floor.

    Returns ``(new_level, new_exp, drained, levels_lost)`` -- ``drained`` is
    the amount actually taken (may be less than ``pts``).
    """
    drained = min(pts, drainable_exp(level, exp))
    remaining = drained
    lost = 0
    while remaining > 0:
        if exp >= remaining:
            exp -= remaining
            remaining = 0
        else:
            remaining -= exp
            exp = mastery_level_cost(level)  # refund the full bracket below
            level -= 1
            lost += 1
    return level, exp, drained, lost


@dataclass
class MasteryGrant:
    """Outcome of a mastery grant, for the player-facing feedback log."""

    pts: int
    levels_gained: int
    category: str | None = None  # display name of the mastery that GAINED
    drained_from: str | None = None  # category/skill name the drain hit
    drained_pts: int = 0
    levels_lost: int = 0  # levels the victim lost (skills may re-lock)


# --- Legion progression ---------------------------------------------------


def legion_level_cost(level: int) -> int:
    """Exp required to advance a legion from ``level - 1`` to ``level``."""
    return level * LEGION_EXP_BASE


def upgrade_ready(level: int, exp: int) -> bool:
    """Banked exp covers the next level (mats checked separately)."""
    return exp >= legion_level_cost(level + 1)


def legion_upgrade_qty(base_qty: int, member_count: int) -> int:
    """Actual material cost for an upgrade sheet entry, scaled by members."""
    return max(1, int(base_qty * max(1, member_count) * LEGION_UPGRADE_QTY_PER_MEMBER))


# --- Loot ------------------------------------------------------------------


def roll_drops(
    drops: Sequence[MobDrop], rolls: int, rng: random.Random | None = None
) -> dict[int, int]:
    """Weighted loot-table picks. Returns ``{material_id: total_qty}``.

    Each roll picks one entry weighted by ``weight``, then rolls quantity
    uniformly in ``[min_qty, max_qty]``.
    """
    if not drops or rolls <= 0:
        return {}
    rng = rng or random
    weights = [d.weight for d in drops]
    result: dict[int, int] = {}
    for _ in range(rolls):
        drop = rng.choices(drops, weights=weights, k=1)[0]
        qty = rng.randint(drop.min_qty, drop.max_qty)
        result[drop.material_id] = result.get(drop.material_id, 0) + qty
    return result


# --- Craft mutation ----------------------------------------------------------


def roll_mutations(
    skill_ids: Sequence[int], legion_level: int, rng: random.Random | None = None
) -> dict[str, int]:
    """Roll an effectiveness % for every skill on a forged weapon.

    Uniform [MUTATION_MIN, MUTATION_MAX], mean shifted up by legion level
    (+MUTATION_LEGION_SHIFT per level, capped). Keys are stringified skill ids
    (JSON round-trip safe).
    """
    rng = rng or random
    shift = min(MUTATION_LEGION_SHIFT_CAP, legion_level * MUTATION_LEGION_SHIFT)
    return {
        str(sid): rng.randint(MUTATION_MIN, MUTATION_MAX) + round(shift)
        for sid in skill_ids
    }


def quality_from_mutations(mutations: dict[str, int]) -> WeaponQuality:
    """Derive the display tier from the mutation average. Flat = STANDARD."""
    if not mutations:
        return WeaponQuality.STANDARD
    avg = sum(mutations.values()) / len(mutations)
    for threshold, tier in QUALITY_TIER_THRESHOLDS:
        if avg >= threshold:
            return WeaponQuality(tier)
    return WeaponQuality.CRUDE


# --- skill value formulas -----------------------------------------------------
# effect_value / stat_bonus_value are STRINGS: "20", "{atk} + 12",
# "{atk}*10% + 20", "{def}*15%". Evaluated safely (AST whitelist, no eval)
# against the actor's stats; N% -> N/100.

import ast as _ast

FORMULA_VARS = ("atk", "attack", "def", "defense", "speed", "hp", "max_hp")

_ALLOWED_NODES = (
    _ast.Expression,
    _ast.BinOp,
    _ast.UnaryOp,
    _ast.Constant,
    _ast.Add,
    _ast.Sub,
    _ast.Mult,
    _ast.Div,
    _ast.USub,
    _ast.UAdd,
)


def eval_formula(expr: str | int | float, stats: dict | None = None) -> int:
    """Resolve a value formula against ``stats``. Plain numbers pass
    through. Unknown variables or disallowed syntax raise ValueError (the
    patch validator catches these at review time)."""
    if isinstance(expr, (int, float)):
        return round(expr)
    s = str(expr)
    stats = stats or {}
    for key in FORMULA_VARS:
        s = s.replace("{" + key + "}", str(stats.get(key, 0)))
    if "{" in s or "}" in s:
        raise ValueError(f"unknown variable in formula: {expr!r}")
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)
    try:
        tree = _ast.parse(s, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"bad formula {expr!r}: {e}") from None
    for node in _ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"disallowed syntax in formula {expr!r}")
        if isinstance(node, _ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError(f"non-numeric constant in formula {expr!r}")
    return round(eval(compile(tree, "<formula>", "eval")))  # noqa: S307 -- whitelisted


def tier_multiplier(tier: int) -> int:
    """Percent multiplier for a skill tier; out-of-range clamps to T1..T5."""
    clamped = SkillTier(max(1, min(SKILL_TIER_MAX, tier or 1)))
    return SKILL_TIER_MULTIPLIERS[clamped]


def tier_scaled(value: int, tier: int) -> int:
    """Apply the tier multiplier to a base effect/stat value."""
    return round(value * tier_multiplier(tier) / 100)


def mutated(value: int, pct: int | None) -> int:
    """Apply a mutation percentage to a skill value (min 0, flat if None)."""
    if pct is None:
        return value
    return max(0, round(value * pct / 100))


# --- Gathering ----------------------------------------------------------------


def bag_hours(gather_level: int) -> int:
    """Max counted AFK hours -- the gather mastery's whole job."""
    return min(
        GATHER_MASTERY_MAX_PER_AFK,
        GATHER_BAG_BASE_HOURS + gather_level * GATHER_BAG_HOURS_PER_LEVEL,
    )


def gather_payout_chunks(elapsed_minutes: int, gather_level: int) -> tuple[int, int]:
    """``(material_chunks, mastery_pts)`` for a stopped session.

    Materials pay per 30-min chunk, mastery +1 per full hour, both capped by
    the bag (counted hours).
    """
    counted = min(elapsed_minutes, bag_hours(gather_level) * 60)
    chunks = counted // GATHER_CHUNK_MINUTES
    pts = min(counted // 60, GATHER_MASTERY_MAX_PER_AFK)
    return chunks, pts
