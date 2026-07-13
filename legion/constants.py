from enum import IntEnum, StrEnum

# Mastery caps -- tuning knobs, expected to rise in future patches.
# Levels up to the soft cap are permanent free growth. Above it, mastery is
# zero-sum: gaining points there drains a random other mastery in the same
# pool (weapon masteries and life skills are separate pools), never below the
# soft-cap floor (level MASTERY_SOFT_CAP, 0 exp).
MASTERY_SOFT_CAP = 5
MASTERY_HARD_CAP = 7
MASTERY_EXP_BASE = 60  # exp to go from level n-1 to n costs n * MASTERY_EXP_BASE
# Inactivity decay: above-soft-cap mastery erodes while a player is away. No
# erosion for the first grace window (generous: a weekend away costs nothing),
# then this many exp/day (lazily applied when the player is next seen), never
# below the soft-cap floor.
MASTERY_EROSION_GRACE_HOURS = 72
MASTERY_EROSION_PER_DAY = 60

# Settlement: mastery pts awarded per dungeon run.
MASTERY_PTS_JOIN = 1
MASTERY_PTS_WIN = 2
MASTERY_PTS_SURVIVED = 2
MASTERY_PTS_TOP_DAMAGE = 1  # competitive: highest damage_dealt (ties all win)
MASTERY_PTS_TOP_TANK = 1  # competitive: highest damage_taken (ties all win)
# Off-hand (sub) weapon also earns mastery, but reduced: sub pts = main // this.
# Granted BEFORE the main hand, so the zero-sum drain eats the sub first.
SUB_WEAPON_MASTERY_DIVISOR = 4

# Outsiders (player.legion != instance.legion): no material drops, mastery
# pts divided (floored, min 1). Non-blocking, surfaced in the settlement log.
OUTSIDER_MASTERY_DIVISOR = 2

DROP_ROLLS_PER_RUN = 1  # weighted loot-table picks per eligible player on a win

# Expeditions: a player starts one, picks a hunting ground (or Random), a
# 60s lobby runs, then the fight fires automatically with whoever joined.
# Difficulty scales off the GROUND's danger rating + party size -- legion
# level only unlocks grounds (no global treadmill).
LOBBY_SECONDS = 60
EXPEDITION_MIN_HP_PCT = 30  # can't start/join an expedition below this % HP
REPLAY_INTERVAL_SECONDS = 2  # delay between round messages in the reply chain

# Venturing into a RANDOM ground pays an explorer's bonus on a win:
RANDOM_GROUND_MASTERY_BONUS = 1  # extra mastery pt for every participant
RANDOM_GROUND_DROP_ROLLS = 2  # replaces DROP_ROLLS_PER_RUN

# Anti-script captcha on /expedition. Heuristic target: robotically REGULAR
# timing -- if consecutive gaps between expeditions match within a tolerance
# enough times in a row, a button test fires. A wrong answer soft-locks the
# player; the lockout DOUBLES each consecutive fail, and after any lockout the
# next attempt is force-tested until a correct answer clears the streak.
CAPTCHA_INTERVAL_TOLERANCE = 5  # seconds: gaps within this count as "regular"
CAPTCHA_STREAK_TRIGGER = 3  # this many regular gaps in a row -> a test
CAPTCHA_BUTTONS = 5  # choices shown (exactly one correct)
CAPTCHA_TIMEOUT_SECONDS = 60  # the view's own timeout
CAPTCHA_LOCKOUT_BASE = 60  # first lockout (seconds); doubles per fail
# Once the doubling lockout would reach this, stop escalating and just
# blacklist the user (in-memory cache, cleared on restart) instead.
CAPTCHA_BLACKLIST_AT_SECONDS = 3600  # 60 min
# Volume heuristic: within a continuous grind session, once consecutive
# expeditions pass the grace count, each further one rolls a GROWING chance of
# a test (+step per run, capped). A pass or a long break resets the counter.
CAPTCHA_RUNS_GRACE = 10  # free consecutive runs before it can fire
CAPTCHA_RUNS_CHANCE_STEP = 0.05  # +5% per run beyond the grace count
CAPTCHA_RUNS_CHANCE_CAP = 0.75  # ceiling on the per-run chance
CAPTCHA_RUNS_RESET_GAP = 3600  # a gap longer than this (s) resets the count

# Settlement presentation: players per embed page (sorted by dealt+taken
# desc); more players -> public paginator + per-presser ephemeral my-result.
SETTLEMENT_PLAYERS_PER_PAGE = 3

# Lobby players shown in the embed (sorted by join time); more players -> public
LOBBY_PLAYERS_SHOWN = 10

# Progress bars (custom head/body/tail emoji in strings.py): total segments
# per bar. Each segment has empty/half/full states -> 2*BAR_LENGTH fill steps.
# Keep <= 10: one custom emoji is ~38 chars and embed fields cap at 1024.
BAR_LENGTH = 10

# Legion progression: exp on cleared runs, weighted by mob tier.
LEGION_EXP_PER_MOB_TIER = 10
LEGION_EXP_BASE = 100  # level n costs n * LEGION_EXP_BASE exp

# Simulation (ATB). Speed fills the gauge each tick; acting costs a full
# gauge. Skill cooldowns count the ACTOR'S OWN TURNS (speed-independent
# rotation); stun and bleed durations are ROUNDS (stun effect_value = turns
# the target loses; a stunned mob's skipped turn does NOT advance the doom
# clock, but DoTs still tick on it -- stunning never pauses your bleeds).
ATB_THRESHOLD = 100  # gauge needed to act; gauge += speed per tick
# Attribute name for the per-command Player-state memo (see
# simulation.cached_player_state); repository.py pops it on equip/dismantle.
SIM_STATE_CACHE_ATTR = "_sim_state_cache"
SIM_MAX_TICKS = 600  # hard stop: unresolved fight counts as a loss
BLEED_DURATION = 3  # bleed deals effect_value once per ROUND, this many rounds
# Status DoTs: each also deals its base effect_value per round (the "_tick"),
# plus a special "_effect" bonus on top.
POISON_DURATION = 3
POISON_PCT_MAX_HP = 0.01  # poison: +1% of the victim's max HP each round
BURN_DURATION = 3
BURN_DOUBLE_CHANCE = 0.30  # burn: 30% chance each round to deal DOUBLE (base again)
FREEZE_DURATION = 3  # freeze lingers this many of the victim's turns
FREEZE_SKIP_CHANCE = 0.30  # freeze: 30% chance to skip each of those turns
PLAYER_BASE_ATK = 10
PLAYER_BASE_DEF = 5
PLAYER_BASE_SPEED = 10
PLAYER_BASE_TAUNT = 0  # aggro is opt-in: 0 base, raised only by TAUNT passives
DEATH_HP = 0  # dead = 0 HP: no natural regen, no food, no active gameplay.

# Mob target selection is WEIGHTED, not uniform: each living player's pull =
# HP_AGGRO_WEIGHT * max_hp + TAUNT_AGGRO_WEIGHT * taunt. HP gives natural
# tankiness (beefy players soak more); the TAUNT stat (from passives) is the
# deliberate lever, scaled up so small passive values still matter vs raw HP.
HP_AGGRO_WEIGHT = 1.0
TAUNT_AGGRO_WEIGHT = 10.0

# Craft workstation embed paginates past this many recipe fields.
CRAFT_SURFACE_PAGE_SIZE = 6

# Mastery page kinds (profile -> mastery select menu).
MASTERY_KIND_WEAPONS = "weapons"
MASTERY_KIND_LIFE = "life"

# Use-item-on-others anti-mule gate: the FEEDER'S total mastery (all pools)
# may trail the target's by at most this percentage. Blocks fresh AFK alts
# farming potions to unlimited-feed a veteran main; a veteran helping a
# newbie downward is always fine.
USE_ITEM_MASTERY_GAP_PCT = 20
# Potions revive instantly; otherwise the revive timer applies.
REVIVE_MINUTES = 30  # auto-revive after this long dead (lazily, at REVIVE_HP)
REVIVE_HP = 1
STARTER_POTION_KEY = "bitter_tonic"  # everyone onboards with 1 (revive safety)

# Starter weapons offered at onboarding (stable KEYS, not display names;
# validate_patch enforces their presence). Starters never mutate --
# intentionally flat 100% skills.
STARTER_WEAPONS: tuple[str, ...] = ("rusty_sword", "vine_bow", "old_staff")

# Per-stack item ceiling, enforced in code on BOTH a player's material stack
# (PlayerMaterial) and the legion stockpile (LegionStockpile). Player-side adds
# clamp at the cap (excess discarded); donations only accept up to the room
# left, leaving the overflow in the donor's bag. Well under the int column max.
MAX_ITEM_STACK = 999_999

# Gathering (AFK). Payouts computed at stop: materials per 20-min chunk,
# gather mastery +1 per full hour, both capped by the "bag" -- the max counted
# hours, which is gather mastery's whole job. Legion level only unlocks sites.
GATHER_CHUNK_MINUTES = 20
GATHER_BAG_BASE_HOURS = 4
GATHER_BAG_HOURS_PER_LEVEL = 2
GATHER_MASTERY_MAX_PER_AFK = 24  # pts cap per session (= 24 counted hours)

# Craft mutation: each skill on a forged weapon rolls its own effectiveness %.
# The item's quality tier is derived from the AVERAGE of its mutations.
# Legion level shifts the roll mean up (+0.5%/level, capped +10).
MUTATION_MIN = 75
MUTATION_MAX = 125
MUTATION_LEGION_SHIFT = 0.5
MUTATION_LEGION_SHIFT_CAP = 10

# Dismantle salvage: from the weapon's flattened crafting cost (1a + 2b ->
# [a, b, b]), each success returns ONE random mat, then re-rolls -- so the
# count is geometric/exponential (prob of returning k = (perc/100)^k). Random
# draws without replacement, so returns never exceed the original cost.
DISMANTLE_RETURN_PERC = 30
QUALITY_TIER_THRESHOLDS = (  # (min average, tier value) checked in order
    (110, "masterwork"),
    (103, "fine"),
    (97, "standard"),
)  # below the last threshold = crude

# Legion upgrades: exp banks automatically from settlements (no auto-level).
# Leveling requires pressing Upgrade with banked exp >= cost AND the stockpile
# covering the material sheet (base_qty scaled by member count).
LEGION_UPGRADE_QTY_PER_MEMBER = 1.0  # actual qty = base_qty * members * this
# Upgrade cost scales by ACTIVE members only: those seen within this window
# (plus never-stamped legacy rows, grandfathered in until they next act).
ACTIVE_WINDOW_DAYS = 7
# Throttle the last_active_at write so it isn't a DB round-trip every command;
# a stamp fresh to the hour is plenty for a 7-day window.
ACTIVE_TOUCH_THROTTLE_MINUTES = 60

# Contribution points (per-legion status; reset when switching legions).
CONTRI_PER_MAT_RARITY = 1  # donating: qty * material.rarity * this
CONTRI_DAILY_FIRST_RUN = 5  # first dungeon fight of the (UTC) day

# Out-of-combat regen: applied lazily whenever the player is fetched.
# HP per minute = base + get_regen_rate(own legion level).
BASE_REGEN_PER_MINUTE = 1

CRAFT_MASTERY_PTS = 1  # cook/brew mastery pts per successful craft

# Craft mastery perk: each cook/brew level adds this chance for a craft to
# produce DOUBLE output. At the hard cap (7) that's 35%.
CRAFT_DOUBLE_CHANCE_PER_LEVEL = 0.05


class SkillTier(IntEnum):
    """Skill tiers scale effect/stat values. Content may write any int;
    anything beyond T5 clamps to T5 (tier_multiplier handles it)."""

    T1 = 1
    T2 = 2
    T3 = 3
    T4 = 4
    T5 = 5


SKILL_TIER_MAX = int(SkillTier.T5)
SKILL_TIER_MULTIPLIERS = {  # percent of base value
    SkillTier.T1: 100,
    SkillTier.T2: 110,
    SkillTier.T3: 120,
    SkillTier.T4: 140,
    SkillTier.T5: 150,
}


class EffectType(StrEnum):
    DAMAGE = "damage"
    HEAL = "heal"
    STUN = "stun"
    BLEED = "bleed"
    POISON = "poison"
    BURN = "burn"
    FREEZE = "freeze"
    SHIELD = "shield"  # self-shield: absorbs damage before HP (combat-only)


class StatBonusType(StrEnum):
    ATK = "atk"
    SPEED = "speed"
    DEF = "def"
    HP = "hp"
    TAUNT = "taunt"  # aggro pull; weights mob target selection (not a combat stat)
    REGEN = "regen"  # HP recovered per minute (out-of-combat); food buff / passive


class RequirementType(StrEnum):
    HP_BELOW = "hp_below"  # HP below a certain %
    PLAYER_DEAD = "player_dead"  # a player has died
    ROUND = "round"  # a certain round is reached


class DungeonStatus(StrEnum):
    ACTIVE = "active"
    CLEARED = "cleared"  # mob defeated
    FAILED = "failed"  # party fought but the mob survived its rounds limit
    EXPIRED = "expired"  # lobby ended with nobody joined
    VOIDED = "voided"  # bot restarted mid-lobby, state cleared


class MaterialKind(StrEnum):
    MATERIAL = "material"  # crafting input
    FOOD = "food"  # alive-only: grants a regen-over-time buff
    POTION = "potion"  # instant heal, small -- and the REVIVE path
    CONSUMABLE = "consumable"  # legacy instant heal (pre food/potion split)
    CHEST = "chest"  # interactable: opens into a bundle (no drops yet)


class LifeSkillType(StrEnum):
    MINE = "mine"  # gather
    GARDEN = "garden"  # gather
    COOK = "cook"  # instant craft
    BREW = "brew"  # instant craft


# Zero-sum drain pools: weapon masteries, gathers, and crafts are THREE
# independent pools -- swording hard never makes you a worse cook, and mining
# never shrinks your brewing.
GATHER_SKILLS = frozenset({LifeSkillType.MINE, LifeSkillType.GARDEN})
CRAFT_SKILLS = frozenset({LifeSkillType.COOK, LifeSkillType.BREW})


class WeaponSlot(StrEnum):
    MAIN = "main"
    SUB = "sub"


class ContentStatus(StrEnum):
    """Lifecycle of a content row. Identity is the stable `key`; display
    names patch freely. DISABLED = pulled from gameplay (spawns, crafting,
    combat snapshots) but data intact -- the kill switch / seasonal lever.
    REMOVED = tombstone: set explicitly via `"_status": "remove"` or
    implicitly when a key disappears from content.py. Rows are never
    hard-deleted (player data references them)."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    REMOVED = "removed"


# content.py `_status` directive -> ContentStatus (absence = enabled).
CONTENT_STATUS_ALIASES = {
    "enable": ContentStatus.ENABLED,
    "enabled": ContentStatus.ENABLED,
    "disable": ContentStatus.DISABLED,
    "disabled": ContentStatus.DISABLED,
    "remove": ContentStatus.REMOVED,
    "removed": ContentStatus.REMOVED,
}


class PatchStatus(StrEnum):
    PENDING = "pending"  # scheduled, timers running
    APPLIED = "applied"
    CANCELLED = "cancelled"


# Graceful update timeline (from pressing Update):
#   lock_at   = start of the next hour  -> session commands blocked
#   apply_at  = lock_at + PATCH_ETA     -> patch applies, everything unlocks
#   freeze_at = apply_at - PATCH_FREEZE -> ALL commands blocked
PATCH_ETA_MINUTES = 60
PATCH_FREEZE_MINUTES = 30


class WeaponQuality(StrEnum):
    CRUDE = "crude"
    STANDARD = "standard"
    FINE = "fine"
    MASTERWORK = "masterwork"
