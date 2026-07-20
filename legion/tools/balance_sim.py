"""Balance Monte-Carlo: content.py builds vs every ground, via the REAL engine.

Run with your project venv (needs the repo's deps installed; touches no DB):
    python balance_sim.py
Works from anywhere INSIDE the repo -- it walks up from its own location to
find the folder containing the `maki` package and puts it on sys.path.
"""
import random
import sys
from pathlib import Path
from types import SimpleNamespace

# Self-locating import bootstrap: Python only adds the SCRIPT'S directory to
# sys.path (not your cwd), so `import maki` fails unless this file sits right
# next to maki/. Walk up until we find it.
for _parent in Path(__file__).resolve().parents:
    if (_parent / "maki" / "__init__.py").exists():
        sys.path.insert(0, str(_parent))
        break
else:
    sys.exit(
        "Couldn't find the `maki` package above this script. Place it inside "
        "the repo (root or maki/cogs/legion/tools/), or run with "
        "PYTHONPATH=/path/to/repo-root."
    )

from maki.cogs.legion.calculator import eval_formula, get_def_bonus, get_hp_bonus, get_mob_stats, tier_multiplier
from maki.cogs.legion.constants import (
    PLAYER_BASE_ATK, PLAYER_BASE_DEF, PLAYER_BASE_SPEED, RESIST_KEYS,
    EffectType, RequirementType, StatBonusType,
)
from maki.cogs.legion.content import PATCH
from maki.cogs.legion.simulation import (
    LoadedSkill, MobState, PassiveRequirement, PlayerState, run_simulation,
    _apply_mob_passive,
)

ACTIVES = {s["key"]: s for s in PATCH["active_skills"]}
PASSIVES = {s["key"]: s for s in PATCH["passive_skills"]}
WEAPONS = {w["key"]: w for w in PATCH["weapons"] if w.get("key")}
MOBS = {m["key"]: m for m in PATCH["mobs"]}
CATS = {c["key"]: c for c in PATCH["categories"]}
GROUNDS = {g["key"]: g for g in PATCH["grounds"]}

_skill_id = {k: i + 1 for i, k in enumerate(ACTIVES)}


def loaded(key, tier=1, cooldown=None, hp_threshold=1.0):
    s = ACTIVES[key]
    obj = SimpleNamespace(id=_skill_id[key], name=s["name"],
                          effect_type=EffectType(s["effect_type"]))
    return LoadedSkill(skill=obj, cooldown=s.get("cooldown", 0) if cooldown is None else cooldown,
                       formula=s["effect_value"], scale=tier_multiplier(tier) / 100,
                       hp_threshold=hp_threshold)


def player(name, weapons, mastery, legion):
    hp = 100 + get_hp_bonus(legion)
    atk, def_, speed, taunt = PLAYER_BASE_ATK, PLAYER_BASE_DEF + get_def_bonus(legion), PLAYER_BASE_SPEED, 0
    base = {"atk": atk, "attack": atk, "def": def_, "defense": def_,
            "speed": speed, "hp": hp, "max_hp": hp, "taunt": taunt}
    skills, resists, cats = [], {}, {}
    for wk in weapons:
        w = WEAPONS[wk]
        cats[w["category"]] = mastery
        for m in w.get("actives", []):
            if m.get("req", 0) <= mastery:
                skills.append(loaded(m["skill"], m.get("tier", 1)))
        for m in w.get("passives", []):
            if m.get("req", 0) > mastery:
                continue
            p = PASSIVES[m["skill"]]
            val = round(eval_formula(p["stat_bonus_value"], base) * tier_multiplier(m.get("tier", 1)) / 100)
            t = p["stat_bonus_type"]
            if t == "hp": hp += val
            elif t == "atk": atk += val
            elif t == "def": def_ += val
            elif t == "speed": speed += val
            elif t == "taunt": taunt += val
            elif t in RESIST_KEYS:
                k = RESIST_KEYS[StatBonusType(t)]
                resists[k] = resists.get(k, 0) + val
    for ck, lvl in cats.items():
        for b in CATS[ck].get("bonus_stat", []):
            if b["level"] > lvl: continue
            t, v = b["stat_bonus_type"], b["value"]
            if t == "hp": hp += v
            elif t == "atk": atk += v
            elif t == "def": def_ += v
            elif t == "speed": speed += v
            elif t == "taunt": taunt += v
    return lambda: PlayerState(name=name, max_hp=hp, current_hp=hp, atk=atk, def_=def_,
                               speed=speed, taunt=taunt, skills=list(skills),
                               resists=dict(resists))


def mob_state(key, danger, n_players):
    m = MOBS[key]
    fake = SimpleNamespace(base_hp=m["hp"], base_atk=m["atk"], base_def=m["def"], base_speed=m["speed"])
    st = get_mob_stats(fake, danger, n_players)
    skills = [loaded(s["skill"], 1, s.get("cooldown", 0), s.get("hp_threshold", 1.0)) for s in m.get("skills", [])]
    ms = MobState(name=m["name"], max_hp=st["hp"], current_hp=st["hp"], atk=st["atk"],
                  def_=st["def"], speed=st["speed"], skills=skills, rounds_limit=m["rounds_limit"])
    for p in m.get("passives", []):
        pd = PASSIVES[p["skill"]]
        sk = SimpleNamespace(name=pd["name"], stat_bonus_type=StatBonusType(pd["stat_bonus_type"]),
                             stat_bonus_value=pd["stat_bonus_value"])
        mp = SimpleNamespace(skill=sk)
        if p.get("requirement_type") is None:
            ms.active_passives.append(mp)
            _apply_mob_passive(ms, mp)
        else:
            ms.pending_requirements.append(PassiveRequirement(
                passive=mp, requirement_type=RequirementType(p["requirement_type"]),
                requirement_value=p.get("requirement_value") or 0.0))
    return ms


def run(ground_key, party_makers, n=400, seed=7):
    g = GROUNDS[ground_key]
    rng = random.Random(seed)
    pool = [( [e["mob"]] if "mob" in e else e["mobs"], e.get("weight", 1)) for e in g["pool"]]
    wins = deaths = rounds_used = fights = timeouts = 0
    hp_left = 0.0
    for _ in range(n):
        packs, weights = zip(*pool)
        pack = rng.choices(packs, weights=weights, k=1)[0]
        party = [mk() for mk in party_makers]
        mobs = [mob_state(k, g["danger"], len(party)) for k in pack]
        r = run_simulation(party, mobs, rng=random.Random(rng.random()))
        fights += 1
        wins += r.won
        timeouts += r.rounded_out
        deaths += sum(1 for p in r.party if not p.alive)
        rounds_used += r.rounds
        if r.won:
            hp_left += sum(max(0, p.current_hp) / p.max_hp for p in r.party) / len(r.party)
    return (wins / fights, deaths / fights / len(party_makers),
            rounds_used / fights, (hp_left / wins if wins else 0), timeouts / fights)


BUILDS = {
    "fresh_sword": player("sword", ["rusty_sword"], 0, 1),
    "fresh_bow": player("bow", ["vine_bow"], 0, 1),
    "fresh_staff": player("staff", ["old_staff"], 0, 1),
    "early_sword": player("sword", ["iron_sword"], 2, 2),
    "early_bow": player("bow", ["vine_bow"], 2, 2),
    "early_staff": player("staff", ["old_staff"], 2, 2),
    "mid_sword": player("sword", ["iron_sword", "stone_shield"], 4, 3),
    "mid_bow": player("bow", ["hunter_bow", "sleeve_arrow"], 4, 3),
    "mid_staff": player("staff", ["golem_staff", "blessed_gloves"], 4, 3),
    "high_sword": player("sword", ["dark_stone_sword", "stone_shield"], 5, 4),
    "high_bow": player("bow", ["flame_lizard_bow", "sleeve_arrow"], 5, 4),
    "high_staff": player("staff", ["golem_staff", "blessed_gloves"], 5, 4),
    "end_sword": player("sword", ["spider_fang_blade", "spider_blade"], 7, 5),
    "end_bow": player("bow", ["spider_web_bow", "sleeve_arrow"], 7, 5),
    "end_staff": player("staff", ["spider_staff", "eye_of_the_spider"], 7, 5),
    "end_tank": player("tank", ["dark_golem_shield", "forged_shield"], 7, 5),
}

MATCHUPS = [
    ("verdant_meadow", ["fresh_sword"]),
    ("verdant_meadow", ["fresh_sword", "fresh_bow", "fresh_staff"]),
    ("whispering_forest", ["early_sword"]),
    ("whispering_forest", ["early_sword", "early_bow", "early_staff"]),
    ("mountain_pass", ["mid_sword", "mid_bow"]),
    ("mountain_pass", ["mid_sword", "mid_bow", "mid_staff"]),
    ("sunken_quarry", ["high_sword", "high_bow", "high_staff"]),
    ("spider_nest", ["high_sword", "high_bow", "high_staff"]),
    ("sunken_quarry", ["mid_sword", "mid_bow", "mid_staff"]),
    ("gloomy_cavern", ["end_sword", "end_bow", "end_staff"]),
    ("gloomy_cavern", ["end_tank", "end_sword", "end_bow", "end_staff"]),
    ("spider_nest_depths", ["end_sword", "end_bow", "end_staff"]),
    ("spider_nest_depths", ["end_tank", "end_sword", "end_bow", "end_staff"]),
    ("spider_nest_depths", ["high_sword", "high_bow", "high_staff"]),
]

print(f"{'ground':20} {'party':42} {'win%':>5} {'death%':>6} {'rounds':>6} {'hp_left':>7} {'timeout%':>8}")
for ground, party in MATCHUPS:
    mk = [BUILDS[b] for b in party]
    w, d, r, hp, t = run(ground, mk)
    print(f"{ground:20} {'+'.join(party):42} {w*100:4.0f}% {d*100:5.0f}% {r:6.1f} {hp*100:6.0f}% {t*100:7.0f}%")

# solo build power snapshot
print("\nbuild stats (atk/def/spd/hp):")
for name, mk in BUILDS.items():
    p = mk()
    print(f"  {name:12} atk{p.atk:3} def{p.def_:3} spd{p.speed:3} hp{p.max_hp:4} skills={len(p.skills)}")
