"""Patch loader: applies the pure-data PATCH from content.py.

Identity = stable `key`; `name` is display-only. `update_or_create` keyed on
`key` throughout, so renames/localization and rebalances land on existing
rows. Join tables (drops, pools, mounts, yields, inputs, upgrade costs) are
fully SYNCED: entries removed from content.py are deleted (safe -- no player
data references them). Keyed parent rows are never hard-deleted: keys absent
from the patch are tombstoned (status=REMOVED), explicit `"_status"` values
apply otherwise. The whole load is atomic.
"""

import hashlib
import json
import re

from tortoise.transactions import in_transaction

from maki.cogs.legion.constants import (
    CONTENT_STATUS_ALIASES,
    STARTER_WEAPONS,
    ContentStatus,
    EffectType,
    LifeSkillType,
    MaterialKind,
    RequirementType,
    StatBonusType,
)
from maki.cogs.legion.calculator import FORMULA_VARS, eval_formula
from maki.cogs.legion.content import PATCH
from maki.cogs.legion.model.model import (
    ActiveSkill,
    GatherSite,
    GroundMob,
    HuntingGround,
    LegionUpgradeCost,
    Material,
    Mob,
    MobDrop,
    MobPassive,
    MobSkill,
    PassiveSkill,
    Recipe,
    RecipeMaterial,
    SiteYield,
    Weapon,
    WeaponActiveSkill,
    WeaponCategory,
    WeaponPassiveSkill,
)

_KEY_RE = re.compile(r"^[a-z0-9_]+$")

# (section, model) for every keyed parent table -- drives the tombstone pass.
_KEYED_SECTIONS = (
    ("materials", Material),
    ("categories", WeaponCategory),
    ("active_skills", ActiveSkill),
    ("passive_skills", PassiveSkill),
    ("weapons", Weapon),
    ("mobs", Mob),
    ("grounds", HuntingGround),
    ("sites", GatherSite),
    ("recipes", Recipe),
)


def content_hash(patch: dict | None = None) -> str:
    """Stable short hash of the content data -- THE patch identity."""
    payload = json.dumps(patch or PATCH, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def content_summary(patch: dict | None = None) -> dict[str, int]:
    """Section counts for the patch embed / diff view."""
    p = patch or PATCH
    return {section: len(p.get(section, [])) for section, _ in _KEYED_SECTIONS} | {
        "upgrade_costs": len(p.get("upgrade_costs", []))
    }


def _status_of(entry: dict) -> ContentStatus:
    return CONTENT_STATUS_ALIASES.get(
        str(entry.get("_status", "enabled")).lower(), ContentStatus.ENABLED
    )


def validate_patch(patch: dict | None = None) -> list[str]:
    """Cross-check every by-key reference in the patch. Returns a list of
    human-readable errors (empty = valid). Pure -- no DB, safe to run in the
    /patch Check step so typos die at review time, not at apply time."""
    p = patch or PATCH
    errors: list[str] = []

    def collect(section: str) -> set[str]:
        seen: set[str] = set()
        for entry in p.get(section, []):
            key = entry.get("key")
            if not key:
                errors.append(
                    f"{section}: entry missing 'key': {entry.get('name', entry)}"
                )
                continue
            if not _KEY_RE.match(key):
                errors.append(f"{section} '{key}': keys must be snake_case [a-z0-9_]")
            if key in seen:
                errors.append(f"{section}: duplicate key '{key}'")
            seen.add(key)
            if not entry.get("name"):
                errors.append(f"{section} '{key}': missing display 'name'")
            if (
                str(entry.get("_status", "enabled")).lower()
                not in CONTENT_STATUS_ALIASES
            ):
                errors.append(
                    f"{section} '{key}': bad _status '{entry.get('_status')}'"
                )
        return seen

    materials = collect("materials")
    categories = collect("categories")
    actives = collect("active_skills")
    passives = collect("passive_skills")
    weapons = collect("weapons")
    mobs = collect("mobs")
    collect("grounds")
    collect("sites")
    collect("recipes")

    def check(section: str, key: str, kind: str, ref: str, pool: set[str]):
        if ref not in pool:
            errors.append(f"{section} '{key}': unknown {kind} '{ref}'")

    valid_effects = {e.value for e in EffectType}
    valid_stats = {s.value for s in StatBonusType}
    valid_kinds = {k.value for k in MaterialKind}
    valid_reqs = {r.value for r in RequirementType}
    gather_skills = {LifeSkillType.MINE.value, LifeSkillType.GARDEN.value}
    craft_skills = {LifeSkillType.COOK.value, LifeSkillType.BREW.value}

    for m in p.get("materials", []):
        if m.get("kind", "material") not in valid_kinds:
            errors.append(f"materials '{m.get('key')}': bad kind '{m.get('kind')}'")
        if m.get("stat_bonus_type") and m["stat_bonus_type"] not in valid_stats:
            errors.append(
                f"materials '{m.get('key')}': bad stat '{m['stat_bonus_type']}'"
            )
        kind = m.get("kind", "material")
        if kind == "food" and (not m.get("stat_bonus_value") or not m.get("duration")):
            errors.append(
                f"materials '{m.get('key')}': food needs stat_bonus_value "
                "(HP/min) and duration (minutes)"
            )
        if kind == "potion" and not m.get("stat_bonus_value"):
            errors.append(f"materials '{m.get('key')}': potion needs stat_bonus_value")
    _dummy_stats = {v: 10 for v in FORMULA_VARS}
    for s in p.get("active_skills", []):
        if s.get("effect_type") not in valid_effects:
            errors.append(
                f"active_skills '{s.get('key')}': bad effect '{s.get('effect_type')}'"
            )
        try:
            eval_formula(s.get("effect_value", 0), _dummy_stats)
        except ValueError as e:
            errors.append(f"active_skills '{s.get('key')}': {e}")
    for s in p.get("passive_skills", []):
        if s.get("stat_bonus_type") not in valid_stats:
            errors.append(
                f"passive_skills '{s.get('key')}': bad stat '{s.get('stat_bonus_type')}'"
            )
        try:
            eval_formula(s.get("stat_bonus_value", 0), _dummy_stats)
        except ValueError as e:
            errors.append(f"passive_skills '{s.get('key')}': {e}")

    for c in p.get("categories", []):
        for b in c.get("bonus_stat", []):
            if b.get("stat_bonus_type") not in valid_stats:
                errors.append(
                    f"categories '{c.get('key')}': bad stat '{b.get('stat_bonus_type')}'"
                )

    for w in p.get("weapons", []):
        check("weapons", w["key"], "category", w.get("category", ""), categories)
        for mount in w.get("actives", []):
            check("weapons", w["key"], "active skill", mount.get("skill", ""), actives)
        for mount in w.get("passives", []):
            check(
                "weapons", w["key"], "passive skill", mount.get("skill", ""), passives
            )

    for m in p.get("mobs", []):
        for sk in m.get("skills", []):
            check("mobs", m["key"], "skill", sk.get("skill", ""), actives)
        for ps in m.get("passives", []):
            check("mobs", m["key"], "passive", ps.get("skill", ""), passives)
            if ps.get("requirement_type") and ps["requirement_type"] not in valid_reqs:
                errors.append(
                    f"mobs '{m['key']}': bad requirement '{ps['requirement_type']}'"
                )
        for d in m.get("drops", []):
            check("mobs", m["key"], "drop material", d.get("material", ""), materials)

    for g in p.get("grounds", []):
        if not g.get("pool"):
            errors.append(f"grounds '{g.get('key')}': empty encounter pool")
        for entry in g.get("pool", []):
            check("grounds", g["key"], "mob", entry.get("mob", ""), mobs)

    for s in p.get("sites", []):
        if s.get("skill") not in gather_skills:
            errors.append(f"sites '{s.get('key')}': skill must be a gather skill")
        for y in s.get("yields", []):
            check("sites", s["key"], "yield material", y.get("material", ""), materials)

    for r in p.get("recipes", []):
        has_weapon, has_material = "weapon" in r, "material" in r
        if has_weapon == has_material:
            errors.append(
                f"recipes '{r.get('key')}': need exactly one of weapon/material"
            )
        if has_weapon:
            check("recipes", r["key"], "result weapon", r["weapon"], weapons)
        if has_material:
            check("recipes", r["key"], "result material", r["material"], materials)
        if r.get("skill") and r["skill"] not in craft_skills:
            errors.append(
                f"recipes '{r.get('key')}': skill must be cook/brew (or absent for forge)"
            )
        for i in r.get("inputs", []):
            check(
                "recipes", r["key"], "input material", i.get("material", ""), materials
            )

    for c in p.get("upgrade_costs", []):
        check(
            "upgrade_costs",
            f"level {c.get('level')}",
            "material",
            c.get("material", ""),
            materials,
        )

    for r in p.get("daily_reward", []):
        check(
            "daily_reward",
            f"threshold {r.get('threshold')}",
            "material",
            r.get("material", ""),
            materials,
        )

    weapon_entries = {w["key"]: w for w in p.get("weapons", []) if w.get("key")}
    for starter in STARTER_WEAPONS:
        if starter not in weapons:
            errors.append(
                f"STARTER_WEAPONS: '{starter}' not in patch weapons -- "
                "onboarding would show no button for it"
            )
        elif not weapon_entries.get(starter, {}).get("main_weapon", True):
            errors.append(
                f"STARTER_WEAPONS: '{starter}' is a sub-hand weapon -- "
                "onboarding equips starters into MAIN"
            )

    return errors


async def pending_removals(patch: dict | None = None) -> dict[str, list[str]]:
    """Keyed DB rows the patch would tombstone (key vanished from content).
    For the /patch review embed -- an accidental key rename shows up here."""
    p = patch or PATCH
    removals: dict[str, list[str]] = {}
    for section, model in _KEYED_SECTIONS:
        patch_keys = {e["key"] for e in p.get(section, []) if e.get("key")}
        stale = (
            await model.filter(key__isnull=False)
            .exclude(key__in=list(patch_keys) or [""])
            .exclude(status=ContentStatus.REMOVED)
        )
        if stale:
            removals[section] = [f"{row.key} ({row.name})" for row in stale]
    return removals


async def apply_patch(patch: dict | None = None) -> int:
    """Validate, then load the patch into the DB atomically. Returns the
    number of NEW rows created. Raises ValueError listing every broken
    reference if validation fails."""
    p = patch or PATCH
    problems = validate_patch(p)
    if problems:
        raise ValueError(
            "Patch validation failed:\n" + "\n".join(f"- {e}" for e in problems)
        )
    async with in_transaction():
        return await _load_sections(p)


async def _load_sections(p: dict) -> int:
    created = 0

    async def put(model, key: dict, values: dict):
        nonlocal created
        _, was_created = await model.update_or_create(**key, defaults=values)
        created += int(was_created)

    async def sync_join(model, parent_field: str, parent_id: int, desired: dict):
        """Upsert `desired` ({other_key_field: (other_id, values)}) and delete
        join rows for this parent that the patch no longer contains."""
        nonlocal created
        keep_ids = []
        for filter_kwargs, values in desired:
            obj, was_created = await model.update_or_create(
                **{parent_field: parent_id}, **filter_kwargs, defaults=values
            )
            created += int(was_created)
            keep_ids.append(obj.id)
        stale = model.filter(**{parent_field: parent_id})
        if keep_ids:
            stale = stale.exclude(id__in=keep_ids)
        await stale.delete()

    # --- keyed parents -----------------------------------------------------
    for m in p.get("materials", []):
        await put(
            Material,
            {"key": m["key"]},
            {
                "name": m["name"],
                "kind": m.get("kind", "material"),
                "rarity": m.get("rarity", 1),
                "stat_bonus_type": m.get("stat_bonus_type"),
                "stat_bonus_value": m.get("stat_bonus_value"),
                "duration": m.get("duration"),
                "description": m.get("description"),
                "status": _status_of(m),
            },
        )
    materials = {mat.key: mat for mat in await Material.filter(key__isnull=False)}

    for c in p.get("categories", []):
        await put(
            WeaponCategory,
            {"key": c["key"]},
            {
                "name": c["name"],
                "status": _status_of(c),
            },
        )
    categories = {c.key: c for c in await WeaponCategory.filter(key__isnull=False)}

    for s in p.get("active_skills", []):
        await put(
            ActiveSkill,
            {"key": s["key"]},
            {
                "name": s["name"],
                "effect_type": s["effect_type"],
                "effect_value": str(s.get("effect_value", 0)),
                "cooldown": s.get("cooldown", 0),
                "status": _status_of(s),
            },
        )
    actives = {s.key: s for s in await ActiveSkill.filter(key__isnull=False)}

    for s in p.get("passive_skills", []):
        await put(
            PassiveSkill,
            {"key": s["key"]},
            {
                "name": s["name"],
                "stat_bonus_type": s["stat_bonus_type"],
                "stat_bonus_value": str(s.get("stat_bonus_value", 0)),
                "status": _status_of(s),
            },
        )
    passives = {s.key: s for s in await PassiveSkill.filter(key__isnull=False)}

    for w in p.get("weapons", []):
        await put(
            Weapon,
            {"key": w["key"]},
            {
                "name": w["name"],
                "category_id": categories[w["category"]].id,
                "description": w.get("description"),
                "main_weapon": w.get("main_weapon", True),
                "status": _status_of(w),
            },
        )
    weapons = {w.key: w for w in await Weapon.filter(key__isnull=False)}

    for w in p.get("weapons", []):
        weapon = weapons[w["key"]]
        await sync_join(
            WeaponActiveSkill,
            "weapon_id",
            weapon.id,
            [
                (
                    {"active_skill_id": actives[m["skill"]].id},
                    {
                        "tier": m.get("tier", 1),
                        "mastery_level_required": m.get("req", 0),
                    },
                )
                for m in w.get("actives", [])
            ],
        )
        await sync_join(
            WeaponPassiveSkill,
            "weapon_id",
            weapon.id,
            [
                (
                    {"passive_skill_id": passives[m["skill"]].id},
                    {
                        "tier": m.get("tier", 1),
                        "mastery_level_required": m.get("req", 0),
                    },
                )
                for m in w.get("passives", [])
            ],
        )

    for m in p.get("mobs", []):
        await put(
            Mob,
            {"key": m["key"]},
            {
                "name": m["name"],
                "tier": m.get("tier", 1),
                "rounds_limit": m.get("rounds_limit", 10),
                "base_hp": m.get("hp", 100),
                "base_atk": m.get("atk", 10),
                "base_def": m.get("def", 5),
                "base_speed": m.get("speed", 1),
                "description": m.get("description"),
                "status": _status_of(m),
            },
        )
    mobs = {m.key: m for m in await Mob.filter(key__isnull=False)}

    for m in p.get("mobs", []):
        mob = mobs[m["key"]]
        await sync_join(
            MobSkill,
            "mob_id",
            mob.id,
            [
                (
                    {"skill_id": actives[sk["skill"]].id},
                    {
                        "cooldown": sk.get("cooldown", 0),
                        "hp_threshold": sk.get("hp_threshold", 1.0),
                    },
                )
                for sk in m.get("skills", [])
            ],
        )
        await sync_join(
            MobPassive,
            "mob_id",
            mob.id,
            [
                (
                    {"skill_id": passives[ps["skill"]].id},
                    {
                        "requirement_type": ps.get("requirement_type"),
                        "requirement_value": ps.get("requirement_value"),
                    },
                )
                for ps in m.get("passives", [])
            ],
        )
        await sync_join(
            MobDrop,
            "mob_id",
            mob.id,
            [
                (
                    {"material_id": materials[d["material"]].id},
                    {
                        "weight": d.get("weight", 1),
                        "min_qty": d.get("min", 1),
                        "max_qty": d.get("max", 1),
                    },
                )
                for d in m.get("drops", [])
            ],
        )

    for g in p.get("grounds", []):
        await put(
            HuntingGround,
            {"key": g["key"]},
            {
                "name": g["name"],
                "danger": g.get("danger", 1),
                "min_legion_level": g.get("min_legion_level", 1),
                "description": g.get("description"),
                "status": _status_of(g),
            },
        )
    grounds = {g.key: g for g in await HuntingGround.filter(key__isnull=False)}
    for g in p.get("grounds", []):
        await sync_join(
            GroundMob,
            "ground_id",
            grounds[g["key"]].id,
            [
                ({"mob_id": mobs[e["mob"]].id}, {"weight": e.get("weight", 1)})
                for e in g.get("pool", [])
            ],
        )

    for s in p.get("sites", []):
        await put(
            GatherSite,
            {"key": s["key"]},
            {
                "name": s["name"],
                "skill": s["skill"],
                "min_legion_level": s.get("min_legion_level", 1),
                "description": s.get("description"),
                "status": _status_of(s),
            },
        )
    sites = {s.key: s for s in await GatherSite.filter(key__isnull=False)}
    for s in p.get("sites", []):
        await sync_join(
            SiteYield,
            "site_id",
            sites[s["key"]].id,
            [
                (
                    {"material_id": materials[y["material"]].id},
                    {
                        "weight": y.get("weight", 1),
                        "min_qty": y.get("min", 1),
                        "max_qty": y.get("max", 1),
                    },
                )
                for y in s.get("yields", [])
            ],
        )

    for r in p.get("recipes", []):
        await put(
            Recipe,
            {"key": r["key"]},
            {
                "name": r["name"],
                "skill": r.get("skill"),
                "mastery_level_required": r.get("req", 0),
                "result_weapon_id": weapons[r["weapon"]].id if "weapon" in r else None,
                "result_material_id": (
                    materials[r["material"]].id if "material" in r else None
                ),
                "result_qty": r.get("qty", 1),
                "status": _status_of(r),
            },
        )
    recipes = {r.key: r for r in await Recipe.filter(key__isnull=False)}
    for r in p.get("recipes", []):
        await sync_join(
            RecipeMaterial,
            "recipe_id",
            recipes[r["key"]].id,
            [
                ({"material_id": materials[i["material"]].id}, {"quantity": i["qty"]})
                for i in r.get("inputs", [])
            ],
        )

    # Upgrade sheet: the patch is authoritative for the WHOLE table.
    keep = []
    for c in p.get("upgrade_costs", []):
        obj, was_created = await LegionUpgradeCost.update_or_create(
            level=c["level"],
            material_id=materials[c["material"]].id,
            defaults={"base_qty": c.get("base_qty", 1)},
        )
        created += int(was_created)
        keep.append(obj.id)
    stale_costs = LegionUpgradeCost.all()
    if keep:
        stale_costs = stale_costs.exclude(id__in=keep)
    await stale_costs.delete()

    # --- tombstone pass: keyed rows whose key vanished from the patch -------
    for section, model in _KEYED_SECTIONS:
        patch_keys = [e["key"] for e in p.get(section, []) if e.get("key")]
        query = model.filter(key__isnull=False).exclude(status=ContentStatus.REMOVED)
        if patch_keys:
            query = query.exclude(key__in=patch_keys)
        await query.update(status=ContentStatus.REMOVED)

    return created


# Back-compat alias (the old bootstrap command used this name).
seed_all = apply_patch
