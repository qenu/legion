"""Unit tests for the pure combat engine (run_simulation): no DB, seeded RNG.

Run from the repo root: ``pytest maki/cogs/legion/tests/``
"""

import random

from maki.cogs.legion.constants import EffectType
from maki.cogs.legion.model.model import ActiveSkill
from maki.cogs.legion.strings import MYSELF_TITLE
from maki.cogs.legion.simulation import (
    DoT,
    LoadedSkill,
    MobState,
    PlayerState,
    run_simulation,
)


def make_player(
    name="hero", hp=100, atk=20, def_=0, speed=10, skills=None
) -> PlayerState:
    return PlayerState(
        name=name,
        max_hp=hp,
        current_hp=hp,
        atk=atk,
        def_=def_,
        speed=speed,
        skills=skills or [],
    )


def make_mob(
    hp=50, atk=5, def_=0, speed=10, rounds_limit=10, skills=None
) -> MobState:
    return MobState(
        name="mob",
        max_hp=hp,
        current_hp=hp,
        atk=atk,
        def_=def_,
        speed=speed,
        skills=skills or [],
        rounds_limit=rounds_limit,
    )


def loaded(skill_id, effect_type, formula, cooldown=0) -> LoadedSkill:
    skill = ActiveSkill(
        id=skill_id,
        name=f"skill{skill_id}",
        effect_type=effect_type,
        effect_value=formula,
        cooldown=cooldown,
    )
    return LoadedSkill(skill=skill, cooldown=cooldown, formula=formula)


def test_party_beats_weak_mob():
    result = run_simulation(
        [make_player()], [make_mob(hp=40, atk=1)], rng=random.Random(1)
    )
    assert result.won
    assert not result.rounded_out
    assert result.party[0].alive


def test_doom_clock_fails_the_fight():
    # Unkillable wall: the mob survives its rounds_limit -> FAILED, not a TPK.
    mob = make_mob(hp=10**6, atk=1, def_=10**6, speed=10, rounds_limit=3)
    result = run_simulation([make_player()], [mob], rng=random.Random(1))
    assert not result.won
    assert result.rounded_out
    assert result.rounds == 3  # the doom clock is exact


def test_rounds_count_only_real_mob_actions():
    mob = make_mob(hp=10**6, atk=1, def_=10**6, speed=10, rounds_limit=2)
    mob.stun_rounds = 3  # pre-stunned: loses 3 turns before acting
    result = run_simulation([make_player()], [mob], rng=random.Random(1))
    stunned = [e for e in result.events if e.kind == "stunned"]
    assert len(stunned) == 3  # the lost turns are logged
    assert result.rounds == 2  # ...but never advanced the doom clock


def test_dots_tick_while_mob_is_stunned():
    # The mob is stunned for its first 3 turns AND bleeding: the bleed must
    # tick through the stun (stunning never pauses the party's DoTs).
    player = make_player(atk=1, speed=1)  # too slow/weak to interfere
    mob = make_mob(hp=1000, atk=0, speed=100, rounds_limit=4)
    mob.stun_rounds = 3
    mob.dots.append(DoT(dmg_per_round=5, rounds_left=3, source=player))
    result = run_simulation([player], [mob], rng=random.Random(1))
    stunned_ticks = {e.tick for e in result.events if e.kind == "stunned"}
    bleed_ticks = {e.tick for e in result.events if e.kind == "bleed_tick"}
    assert bleed_ticks & stunned_ticks  # a tick where BOTH happened
    assert player.damage_dealt >= 15  # all 3 bleed rounds credited


def test_target_namespace_formula_hits_for_percent_of_max():
    # "{target.max_health}*10%" vs a 200-HP, 0-def mob -> 20 damage per use.
    skill = loaded(1, EffectType.DAMAGE, "{target.max_health}*10%", cooldown=0)
    player = make_player(atk=1, skills=[skill])
    mob = make_mob(hp=200, atk=0, speed=1, rounds_limit=10**6)
    result = run_simulation([player], [mob], rng=random.Random(1))
    assert result.won
    hits = [e for e in result.events if e.kind == "skill"]
    assert hits and all(e.value == 20 for e in hits)


def test_heal_targets_lowest_ally():
    healer_skill = loaded(2, EffectType.HEAL, "50", cooldown=0)
    healer = make_player(name="healer", hp=100, atk=1, skills=[healer_skill])
    tank = make_player(name="tank", hp=100, atk=1)
    tank.current_hp = 10  # clearly the lowest ratio
    mob = make_mob(hp=10**6, atk=0, def_=10**6, speed=10, rounds_limit=2)
    result = run_simulation([healer, tank, ], [mob], rng=random.Random(1))
    heals = [e for e in result.events if e.kind == "heal"]
    assert heals and heals[0].target == "tank"
    assert tank.current_hp > 10


def test_cooldowns_run_from_the_start():
    # cd-3 skill must NOT fire on turn one -- no opening alpha strike.
    skill = loaded(3, EffectType.DAMAGE, "999", cooldown=3)
    player = make_player(atk=1, skills=[skill])
    mob = make_mob(hp=10**6, atk=0, def_=0, speed=10, rounds_limit=1)
    result = run_simulation([player], [mob], rng=random.Random(1))
    first_player_events = [
        e for e in result.events if e.actor == "hero" and e.kind in ("skill", "attack")
    ]
    assert first_player_events[0].kind == "attack"  # basic attack, not the nuke


def test_shield_absorbs_before_hp():
    # Mob hits for exactly 10 (atk 10, def 0). A 25-pt shield eats the first
    # two hits and half the third; HP only starts dropping then.
    player = make_player(hp=100, atk=1, def_=0, speed=1)
    player.shield = 25
    mob = make_mob(hp=10**6, atk=10, def_=10**6, speed=100, rounds_limit=3)
    result = run_simulation([player], [mob], rng=random.Random(1))
    assert player.shield == 0
    assert player.current_hp == 95  # 3 hits x10 = 30; 25 shielded, 5 to HP
    assert player.damage_taken == 30  # stats count the FULL damage


def test_shield_absorbs_dots():
    player = make_player(hp=100, atk=1, speed=1)
    player.shield = 100
    player.dots.append(DoT(dmg_per_round=7, rounds_left=2, source=player))
    mob = make_mob(hp=10**6, atk=0, def_=10**6, speed=100, rounds_limit=3)
    run_simulation([player], [mob], rng=random.Random(1))
    assert player.current_hp == 100  # the shield soaked every bleed tick
    # 2 bleed ticks x7 + the mob's 3 min-1 chip hits = 17, all shielded.
    assert player.damage_taken == 17
    assert player.shield == 100 - 17


def test_shield_skill_grants_and_refreshes_without_stacking():
    # cd-0 shield "{player.defense}*2 + 10" with def 20 -> 50 pts, every turn.
    skill = loaded(5, EffectType.SHIELD, "{player.defense}*2 + 10", cooldown=0)
    player = make_player(hp=100, atk=1, def_=20, speed=10, skills=[skill])
    # speed 0: the mob never acts; the fight ends at the tick limit.
    mob = make_mob(hp=10**6, atk=0, def_=10**6, speed=0, rounds_limit=10**6)
    result = run_simulation([player], [mob], rng=random.Random(1))
    applied = [e for e in result.events if e.kind == "shield_applied"]
    assert applied and all(e.value == 50 for e in applied)
    assert player.shield == 50  # re-casts refresh, never stack past the roll


def test_pack_won_only_when_every_mob_dies():
    pack = [make_mob(hp=40, atk=1), make_mob(hp=40, atk=1)]
    result = run_simulation([make_player(atk=30)], pack, rng=random.Random(1))
    assert result.won
    assert all(not m.alive for m in result.mobs)


def test_pack_doom_clock_is_max_rounds_limit():
    # Limits 2 and 5: the pack's clock runs to 5 (leader = first living mob).
    pack = [
        make_mob(hp=10**6, atk=1, def_=10**6, speed=10, rounds_limit=2),
        make_mob(hp=10**6, atk=1, def_=10**6, speed=10, rounds_limit=5),
    ]
    result = run_simulation([make_player()], pack, rng=random.Random(1))
    assert not result.won and result.rounded_out
    assert result.rounds == 5


def test_pack_leader_death_promotes_next_mob():
    # Kill the fragile leader; the tough second mob keeps closing rounds and
    # the doom clock still runs out exactly.
    pack = [
        make_mob(hp=10, atk=1, speed=10, rounds_limit=3),
        make_mob(hp=10**6, atk=1, def_=10**6, speed=10, rounds_limit=3),
    ]
    result = run_simulation([make_player(atk=50)], pack, rng=random.Random(1))
    assert not result.won and result.rounded_out
    assert not result.mobs[0].alive and result.mobs[1].alive
    assert result.rounds == 3


def test_pack_random_targeting_spreads_damage():
    # Plenty of attacks against two identical tanky mobs: both get hit.
    pack = [
        make_mob(hp=10**6, atk=0, def_=0, speed=1, rounds_limit=10**6),
        make_mob(hp=10**6, atk=0, def_=0, speed=1, rounds_limit=10**6),
    ]
    run_simulation([make_player(atk=10)], pack, rng=random.Random(7))
    assert pack[0].damage_taken > 0 and pack[1].damage_taken > 0


def test_pack_is_a_team_never_attacks_itself():
    # A pack with a full offensive kit + a healer: every damaging/offensive
    # event must land on a player; heals must stay inside the pack.
    kit = [
        loaded(10, EffectType.DAMAGE, "{atk} + 5", cooldown=1),
        loaded(11, EffectType.STUN, "1", cooldown=2),
        loaded(12, EffectType.BLEED, "{atk}*30%", cooldown=2),
    ]
    healer = [loaded(13, EffectType.HEAL, "30", cooldown=1)]
    bruiser = make_mob(hp=500, atk=10, speed=10, rounds_limit=10, skills=kit)
    medic = make_mob(hp=500, atk=5, speed=10, rounds_limit=10, skills=healer)
    medic.name = "medic"
    medic.current_hp = 100  # clearly the pack's lowest -- heal bait
    party = [make_player(hp=400, atk=5)]
    result = run_simulation(party, [bruiser, medic], rng=random.Random(3))

    mob_names = {"mob", "medic"}
    offensive = ("skill", "attack", "stun", "bleed", "poison", "burn", "freeze")
    for e in result.events:
        if e.actor in mob_names and e.kind in offensive:
            assert e.target == "hero"  # offense only ever lands on players
    heals = [e for e in result.events if e.actor in mob_names and e.kind == "heal"]
    assert heals  # the medic did its job...
    for e in heals:
        assert e.target in mob_names | {MYSELF_TITLE}  # ...and only on the pack


def test_deterministic_given_seed():
    def go():
        skill = loaded(4, EffectType.BLEED, "{atk}*30%", cooldown=2)
        return run_simulation(
            [make_player(skills=[skill])],
            [make_mob(hp=80, atk=8, speed=8)],
            rng=random.Random(1234),
        )

    a, b = go(), go()
    assert a.won == b.won and a.ticks == b.ticks
    assert [(e.tick, e.kind, e.value) for e in a.events] == [
        (e.tick, e.kind, e.value) for e in b.events
    ]
