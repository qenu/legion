"""Unit tests for render helpers that have burned us before.

Run from the repo root: ``pytest maki/cogs/legion/tests/``
"""

import discord

from maki.cogs.legion.render import (
    BLANK_FIELD_NAME,
    EMBED_FIELD_VALUE_LIMIT,
    _round_fields,
    combat_log_embeds,
)
from maki.cogs.legion.simulation import CombatEvent, SimulationResult


def test_round_fields_split_on_line_boundaries():
    name = "第 1 回合"
    lines = [f"**player{i}** 攻擊了 **mob** 造成 **123** 點傷害" for i in range(60)]
    fields = _round_fields(name, lines)
    assert len(fields) > 1  # 60 long lines cannot fit one field
    assert fields[0][0] == name
    assert all(f[0] == BLANK_FIELD_NAME for f in fields[1:])
    for _, value in fields:
        assert len(value) <= EMBED_FIELD_VALUE_LIMIT
        assert not value.startswith("\n") and not value.endswith("\n")
    # nothing lost in the split
    assert "\n".join(v for _, v in fields) == "\n".join(lines)


def test_round_fields_short_round_untouched():
    fields = _round_fields("第 2 回合", ["a", "b"])
    assert fields == [("第 2 回合", "a\nb")]


def test_dot_events_collapse_per_victim_per_flavor():
    from maki.cogs.legion.render import _collapse_dot_events

    events = [
        CombatEvent(tick=1, round=1, actor="hero", kind="poison_tick", value=5),
        CombatEvent(tick=1, round=1, actor="hero", kind="poison_effect", value=2),
        CombatEvent(tick=1, round=1, actor="hero", kind="bleed_tick", value=7),
        CombatEvent(tick=1, round=1, actor="mob", kind="poison_tick", value=9),
        CombatEvent(tick=1, round=1, actor="hero", kind="attack", target="mob", value=3),
        CombatEvent(tick=2, round=1, actor="mob", kind="freeze_effect", value=0),  # skip
    ]
    out = _collapse_dot_events(events)
    kinds = [(e.actor, e.kind, e.value) for e in out]
    assert ("hero", "poison_tick", 7) in kinds  # 5 tick + 2 spread summed
    assert ("hero", "bleed_tick", 7) in kinds  # different flavor stays apart
    assert ("mob", "poison_tick", 9) in kinds  # different victim stays apart
    assert ("hero", "attack", 3) in kinds  # non-DoT untouched
    assert ("mob", "freeze_effect", 0) in kinds  # the skip is not damage
    assert len(out) == 5
    # source events were never mutated
    assert events[0].value == 5


def test_combat_log_embeds_respect_field_cap():
    # A monster fight: 3 rounds x 80 verbose events -- every produced field
    # must sit under Discord's 1024 cap and every embed under ~6000 chars.
    events = [
        CombatEvent(
            tick=r * 100 + i,
            round=r,
            actor=f"很長名字的玩家{i % 8}",
            kind="attack",
            target="石像巨人",
            value=12345,
        )
        for r in range(1, 4)
        for i in range(80)
    ]
    result = SimulationResult(
        won=True, ticks=300, rounds=3, rounded_out=False,
        party=[], mobs=[], events=events,
    )
    embeds = combat_log_embeds(result, 6, discord.Colour.blue())
    assert embeds
    for embed in embeds:
        assert embed.fields  # never an empty page
        for f in embed.fields:
            assert f.name  # Discord rejects empty names (blank = ZWSP)
            assert len(f.value) <= EMBED_FIELD_VALUE_LIMIT
        total = sum(len(f.name) + len(f.value) for f in embed.fields)
        assert total <= 6000
