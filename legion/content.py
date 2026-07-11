"""Game content as pure data -- THE patch.

Identity is the stable `key` (snake_case, never changes); `name` is display
text and patches freely (rename/localize at will). All cross-references use
keys. Lifecycle: add `"_status": "disable"` to pull something from gameplay
without touching player data, `"remove"` to tombstone explicitly -- and any
key that simply DISAPPEARS from this file is tombstoned automatically at
apply (rows are never hard-deleted; the /patch review shows removals).
"""

PATCH: dict = {
    "version": "0.1.16",
    "notes": "Patch 0.1.16: Added new materials, mobs, and recipes for Legion content.",
    "materials": [
        {"key": "iron_ore", "name": "鐵礦石", "rarity": 1,
         "description": "帶著鏽色紋路的礦石，鍛造的基礎。"},
        {"key": "rough_stone", "name": "粗礦石", "rarity": 1,
         "description": "未經雕琢的石塊，堆起來就是牆。"},
        {"key": "sunherb", "name": "日光草", "rarity": 1,
         "description": "向著太陽生長的藥草，氣味清香。"},
        {"key": "duskberry", "name": "野莓果", "rarity": 1,
         "description": "黃昏時分採摘最甜，小心別吃太多。"},
        {"key": "boar_hide", "name": "野豬皮", "rarity": 2,
         "description": "厚實耐磨，是護具與握柄的好材料。"},
        {"key": "slime_goo", "name": "史萊姆黏液", "rarity": 1,
         "description": "黏糊糊的，據說軍團的倉庫牆縫全靠它。"},
        {"key": "wolf_fang", "name": "狼牙", "rarity": 2,
         "description": "鋒利依舊，彷彿還帶著低沉的咆哮。"},
        {"key": "wolf_hide", "name": "狼皮", "rarity": 2,
         "description": "厚實耐磨，是護具與握柄的好材料。"},
        {"key": "golem_core", "name": "魔像核心", "rarity": 3,
         "description": "仍在微微發燙的核心，蘊含古老的力量。"},
        {"key": "hearty_stew", "name": "燉菜", "kind": "food", "rarity": 1,
         "stat_bonus_type": "hp", "stat_bonus_value": 2, "duration": 30,
         "description": "熱騰騰的一鍋，喝下去暖到骨子裡。"},
        {"key": "bitter_tonic", "name": "苦藥水", "kind": "potion", "rarity": 2,
         "stat_bonus_type": "hp", "stat_bonus_value": 40,
         "description": "苦到皺眉，但能把人從鬼門關拉回來。"},
        {"key": "healing_potion", "name": "治癒藥水", "kind": "potion", "rarity": 1,
         "stat_bonus_type": "hp", "stat_bonus_value": 5, 
         "description": "小小一瓶，能快速回復少量生命。"},
        {"key": "rabbit_foot", "name": "兔腳", "rarity": 2,
         "description": "傳說中能帶來好運的兔腳，摸起來軟軟的。"},
        {"key": "lizard_tail", "name": "蜥蜴尾巴", "rarity": 2,
         "description": "斷掉的尾巴仍在微微蠕動，彷彿還能咬人。"},
        {"key": "molt_skin", "name": "脫落的皮", "rarity": 2,
         "description": "脫落的皮，感覺有點噁心。"},
        {"key": "spring_roll", "name": "春捲", "kind": "food", "rarity": 2,
         "stat_bonus_type": "hp", "stat_bonus_value": 3, "duration": 30,
         "description": "半透明的外皮，裡面包著各種蔬菜，吃起來清爽。"},
        {"key": "flame_lizard_core", "name": "火蜥蜴核心", "rarity": 3,
            "description": "仍在微微發燙的核心，蘊含古老的火焰力量。"},
        {"key": "dark_golem_core", "name": "黑石魔像核心", "rarity": 3,
            "description": "仍在微微發燙的核心，蘊含古老的黑暗力量。"},
        {"key": "cobweb", "name": "蜘蛛網", "rarity": 1,
            "description": "蜘蛛吐出的絲，黏黏的，能用來製作一些東西。"},
        {"key": "spider_fang", "name": "蜘蛛牙", "rarity": 2,
            "description": "鋒利的蜘蛛牙，帶有微弱的毒性。"},
        {"key": "rabbit_porridge", "name": "兔肉粥", "kind": "food", "rarity": 2,
         "stat_bonus_type": "hp", "stat_bonus_value": 5, "duration": 30,
            "description": "神秘的兔肉粥，非常的黏稠美味。"},
        {"key": "thick_bark", "name": "厚樹皮", "rarity": 2,
            "description": "堅硬的樹皮，可以用來製作防具。"},
        {"key": "raspberry", "name": "樹莓", "rarity": 2,
            "description": "酸甜的樹莓，吃起來非常爽口。"},
    ],
    "categories": [
        {"key": "sword", "name": "刀劍"},
        {"key": "bow", "name": "弓箭"},
        {"key": "staff", "name": "法器"},
        {"key": "shield", "name": "盾牌"},
    ],
    "active_skills": [
        {"key": "slash", "name": "斬擊", "effect_type": "damage", "effect_value": "{atk} + 6", "cooldown": 1},
        {"key": "cleave", "name": "劈砍", "effect_type": "damage", "effect_value": "{atk} + 12", "cooldown": 3},
        {"key": "piercing_shot", "name": "穿刺射擊", "effect_type": "damage", "effect_value": "{atk} + 12", "cooldown": 1},
        {"key": "barbed_arrow", "name": "帶刺箭", "effect_type": "bleed", "effect_value": "{atk}*30%", "cooldown": 3},
        {"key": "spark", "name": "火花", "effect_type": "damage", "effect_value": "{atk} + 6", "cooldown": 1},
        {"key": "mend", "name": "治癒", "effect_type": "heal", "effect_value": "{atk} + 5", "cooldown": 3},
        {"key": "dazing_blow", "name": "眩暈打擊", "effect_type": "stun", "effect_value": 1, "cooldown": 3},
        {"key": "smash", "name": "粉碎", "effect_type": "damage", "effect_value": "{atk} + 8", "cooldown": 2},
        {"key": "rending_howl", "name": "撕裂咆哮", "effect_type": "bleed", "effect_value": "{atk}*30%", "cooldown": 3},
        {"key": "quake", "name": "震攝", "effect_type": "damage", "effect_value": "{atk} + 15", "cooldown": 3},
        {"key": "rock_throw", "name": "投擲碎石", "effect_type": "damage", "effect_value": "{atk} + 10", "cooldown": 2},
        {"key": "flame_throw", "name": "火焰噴射", "effect_type": "damage", "effect_value": "{atk} + 20", "cooldown": 3},
        {"key": "poison_fang", "name": "毒牙", "effect_type": "poison", "effect_value": "{atk}*20%", "cooldown": 3},
        {"key": "focus_shot", "name": "專注射擊", "effect_type": "damage", "effect_value": "{atk} + 15", "cooldown": 1},
        {"key": "flame_arrow", "name": "火焰箭", "effect_type": "burn", "effect_value": "{atk}*20%", "cooldown": 3},
    ],
    "passive_skills": [
        {"key": "grit", "name": "堅毅", "stat_bonus_type": "hp", "stat_bonus_value": 20},
        {"key": "fleetfoot", "name": "迅捷", "stat_bonus_type": "speed", "stat_bonus_value": 3},
        {"key": "focus", "name": "專注", "stat_bonus_type": "atk", "stat_bonus_value": 5},
        {"key": "thick_hide", "name": "堅硬", "stat_bonus_type": "def", "stat_bonus_value": 4},
        {"key": "enrage", "name": "狂怒", "stat_bonus_type": "atk", "stat_bonus_value": 15},
        {"key": "haste", "name": "加速", "stat_bonus_type": "speed", "stat_bonus_value": 5},
        {"key": "provoke", "name": "挑釁", "stat_bonus_type": "taunt", "stat_bonus_value": 6},
        {"key": "exoskeletal", "name": "外骨骼", "stat_bonus_type": "def", "stat_bonus_value": 8},
    ],
    "weapons": [
        {
            "key": "rusty_sword", "name": "生鏽長劍", "category": "sword",
            "actives": [{"skill": "slash", "tier": 1, "req": 0}],
            "passives": [{"skill": "grit", "tier": 1, "req": 0}]
        },
        {
            "key": "vine_bow", "name": "藤蔓弓", "category": "bow",
            "actives": [{"skill": "piercing_shot", "tier": 1, "req": 0},
                     {"skill": "barbed_arrow", "tier": 2, "req": 2}],
            "passives": [{"skill": "fleetfoot", "tier": 1, "req": 0}]
        },
        {   "key": "old_staff", "name": "老舊法杖", "category": "staff",
            "actives": [{"skill": "spark", "tier": 1, "req": 0},
                     {"skill": "mend", "tier": 1, "req": 1}],
            "passives": []
        },
        {
            "key": "iron_sword", "name": "鐵劍", "category": "sword",
            "actives": [{"skill": "slash", "tier": 2, "req": 0},
                     {"skill": "cleave", "tier": 2, "req": 2},
                     {"skill": "dazing_blow", "tier": 1, "req": 4}],
            "passives": [{"skill": "grit", "tier": 1, "req": 0},
                      {"skill": "focus", "tier": 2, "req": 3}]
        },
        {
            "key": "fang_dagger", "name": "狼牙短刀", "category": "sword", 
            "actives": [{"skill": "slash", "tier": 1, "req": 1}],
            "passives": [{"skill": "fleetfoot", "tier": 1, "req": 2}],
            "main_weapon": False, # sub-hand; shares sword mastery
        },  
        {
            "key": "golem_staff", "name": "魔像法杖", "category": "staff",
            "actives": [{"skill": "rock_throw", "tier": 2, "req": 3},
                      {"skill": "mend", "tier": 2, "req": 3},
                      {"skill": "quake", "tier": 2, "req": 4}],
            "passives": [{"skill": "focus", "tier": 2, "req": 3},]
        },
        {
            "key": "hunter_bow", "name": "獵弓", "category": "bow",
            "actives": [{"skill": "piercing_shot", "tier": 3, "req": 2},
                       {"skill": "barbed_arrow", "tier": 3, "req": 3}],
            "passives": [{"skill": "fleetfoot", "tier": 2, "req": 2},
                        {"skill": "focus", "tier": 2, "req": 2}]},
        {
            "key": "stone_shield", "name": "石盾", "category": "shield",
            "actives": [{"skill": "quake", "tier": 1, "req": 4}],
            "passives": [{"skill": "thick_hide", "tier": 1, "req": 1},
                         {"skill": "grit", "tier": 1, "req": 0}],
            "main_weapon": False,
        },
        {
            "key": "blessed_gloves", "name": "祝福手套", "category": "staff",
            "actives": [{"skill": "mend", "tier": 1, "req": 2}],
            "passives": [{"skill": "focus", "tier": 1, "req": 2}],
            "main_weapon": False,
        },
        {
            "key": "flame_lizard_staff", "name": "火蜥蜴法杖", "category": "staff",
            "actives": [{"skill": "spark", "tier": 3, "req": 2},
                      {"skill": "flame_throw", "tier": 2, "req": 4}],
            "passives": [{"skill": "focus", "tier": 2, "req": 3}],
        },
        {
            "key": "dark_stone_sword", "name": "黑石巨劍", "category": "sword",
            "actives": [{"skill": "slash", "tier": 3, "req": 2},
                      {"skill": "cleave", "tier": 3, "req": 4},
                      {"skill": "smash", "tier": 2, "req": 5}],
            "passives": [{"skill": "grit", "tier": 2, "req": 3},
                      {"skill": "focus", "tier": 2, "req": 3},
                      {"skill": "enrage", "tier": 1, "req": 5}],
        },
        {
            "key": "sleeve_arrow", "name": "袖箭", "category": "bow",
            "actives": [{"skill": "piercing_shot", "tier": 1, "req": 2}],
            "passives": [{"skill": "fleetfoot", "tier": 1, "req": 3}],
            "main_weapon": False,
        },
        {
            "key": "flame_lizard_bow", "name": "火蜥弓", "category": "bow",
            "actives": [{"skill": "focus_shot", "tier": 2, "req": 2},
                       {"skill": "flame_arrow", "tier": 2, "req": 3}],
            "passives": [{"skill": "fleetfoot", "tier": 2, "req": 2},
                        {"skill": "focus", "tier": 2, "req": 3},
                        {"skill": "haste", "tier": 1, "req": 4}],
        },
    ],
    "mobs": [
        {
            "key": "slime", "name": "史萊姆", "tier": 1, "rounds_limit": 8,
            "hp": 30, "atk": 6, "def": 2, "speed": 6,
            "skills": [], "passives": [],
            "drops": [
                {"material": "slime_goo", "weight": 3, "min": 1, "max": 2},
                {"material": "sunherb", "weight": 1, "min": 1, "max": 1}]
        },
        {
            "key": "wild_boar", "name": "野豬", "tier": 1, "rounds_limit": 8,
            "hp": 60, "atk": 11, "def": 6, "speed": 8,
            "skills": [
                {"skill": "smash", "cooldown": 2, "hp_threshold": 1.0}],
            "passives": [],
            "drops": [
                {"material": "boar_hide", "weight": 3, "min": 1, "max": 2},
                {"material": "duskberry", "weight": 1, "min": 1, "max": 1}]},
        {
            "key": "wild_rabbit", "name": "野兔", "tier": 1, "rounds_limit": 8,
            "hp": 20, "atk": 4, "def": 1, "speed": 10,
            "skills": [], 
            "passives": [
                {"skill": "fleetfoot", "requirement_type": "hp_below","requirement_value": 0.7}
            ],
            "drops": [
                {"material": "sunherb", "weight": 2, "min": 1, "max": 1},
                {"material": "rabbit_foot", "weight": 1, "min": 1, "max": 1}]
        },
        {   
            "key": "grey_wolf", "name": "灰狼", "tier": 2, "rounds_limit": 7,
            "hp": 80, "atk": 13, "def": 3, "speed": 12,
            "skills": [
                {"skill": "rending_howl", "cooldown": 3, "hp_threshold": 1.0}],
            "passives": [
                {"skill": "enrage", "requirement_type": "hp_below","requirement_value": 0.4}],
            "drops": [
                {"material": "wolf_fang", "weight": 3, "min": 1, "max": 2},
                {"material": "wolf_hide", "weight": 1, "min": 1, "max": 1}]
        },
        {
            "key": "dire_wolf", "name": "兇狼", "tier": 2, "rounds_limit": 7,
            "hp": 120, "atk": 18, "def": 5, "speed": 14,
            "skills": [
                {"skill": "rending_howl", "cooldown": 3, "hp_threshold": 1.0}],
            "passives": [
                {"skill": "enrage", "requirement_type": "hp_below","requirement_value": 0.7},
                {"skill": "haste", "requirement_type": "hp_below","requirement_value": 0.4}],
            "drops": [
                {"material": "wolf_fang", "weight": 3, "min": 1, "max": 2},
                {"material": "wolf_hide", "weight": 2, "min": 1, "max": 2}]
        },
        {
            "key": "flame_lizard", "name": "火蜥蜴", "tier": 2, "rounds_limit": 7,
            "hp": 90, "atk": 14, "def": 4, "speed": 10,
            "skills": [
                {"skill": "spark", "cooldown": 0, "hp_threshold": 1.0}],
            "passives": [],
            "drops": [
                {"material": "lizard_tail", "weight": 3, "min": 1, "max": 1},
                {"material": "molt_skin", "weight": 2, "min": 1, "max": 2}]
        },
        {
            "key": "giant_flame_lizard", "name": "巨型火蜥蜴", "tier": 2, "rounds_limit": 7,
            "hp": 150, "atk": 20, "def": 6, "speed": 8,
            "skills": [
                {"skill": "flame_throw", "cooldown": 1, "hp_threshold": 1.0},
                {"skill": "dazing_blow", "cooldown": 2, "hp_threshold": 0.5}],
            "passives": [],
            "drops": [
                {"material": "lizard_tail", "weight": 3, "min": 1, "max": 3},
                {"material": "molt_skin", "weight": 3, "min": 1, "max": 3},
                {"material": "flame_lizard_core", "weight": 2, "min": 1, "max": 2}]
        },
        {
            "key": "flower_slime", "name": "花朵史萊姆", "tier": 2, "rounds_limit": 7,
            "hp": 70, "atk": 12, "def": 3, "speed": 9,
            "skills": [
                {"skill": "mend", "cooldown": 1, "hp_threshold": 0.5}],
            "passives": [],
            "drops": [
                {"material": "slime_goo", "weight": 3, "min": 1, "max": 2},
                {"material": "sunherb", "weight": 2, "min": 1, "max": 2}]
        },
        {
            "key": "stone_golem", "name": "石像巨人", "tier": 3, "rounds_limit": 6,
            "hp": 250, "atk": 15, "def": 15, "speed": 3,
            "skills": [
                {"skill": "quake", "cooldown": 3, "hp_threshold": 0.7}],
            "passives": [
                {"skill": "thick_hide", "requirement_type": "hp_below","requirement_value": 0.8}],
            "drops": [
                {"material": "golem_core", "weight": 1, "min": 1, "max": 1},
                {"material": "rough_stone", "weight": 3, "min": 2, "max": 4},
                {"material": "iron_ore", "weight": 2, "min": 1, "max": 2}]
        },
        {
            "key": "dark_stone_golem", "name": "黑石巨人", "tier": 3, "rounds_limit": 6,
            "hp": 300, "atk": 20, "def": 20, "speed": 4,
            "skills": [
                {"skill": "quake", "cooldown": 3, "hp_threshold": 0.7},
                {"skill": "rock_throw", "cooldown": 2, "hp_threshold": 1.0}],
            "passives": [
                {"skill": "thick_hide", "requirement_type": "hp_below","requirement_value": 0.8},
                {"skill": "provoke", "requirement_type": "hp_below","requirement_value": 0.5}],
            "drops": [
                {"material": "dark_golem_core", "weight": 1, "min": 1, "max": 1},
                {"material": "rough_stone", "weight": 3, "min": 2, "max": 4},
                {"material": "iron_ore", "weight": 2, "min": 1, "max": 2}]
        },
        {
            "key": "rock_slime", "name": "碎石史萊姆", "tier": 2, "rounds_limit": 5,
            "hp": 80, "atk": 10, "def": 5, "speed": 8,
            "skills": [
                {"skill": "rock_throw", "cooldown": 2, "hp_threshold": 1.0}],
            "passives": [],
            "drops": [
                {"material": "iron_ore", "weight": 1, "min": 1, "max": 2},
                {"material": "slime_goo", "weight": 2, "min": 1, "max": 2}]
        },
        {
            "key": "spider", "name": "蜘蛛", "tier": 2, "rounds_limit": 6,
            "hp": 60, "atk": 10, "def": 2, "speed": 8,
            "skills": [
                {"skill": "slash", "cooldown": 1, "hp_threshold": 1.0}],
            "passives": [],
            "drops": [
                {"material": "cobweb", "weight": 2, "min": 1, "max": 2},
                {"material": "thick_bark", "weight": 1, "min": 1, "max": 1}]
        },
        {
            "key": "cave_spider", "name": "洞穴蜘蛛", "tier": 2, "rounds_limit": 6,
            "hp": 70, "atk": 12, "def": 3, "speed": 10,
            "skills": [
                {"skill": "poison_fang", "cooldown": 1, "hp_threshold": 1.0}],
            "passives": [
                {"skill": "exoskeletal", "requirement_type": "hp_below","requirement_value": 0.5}
            ],
            "drops": [
                {"material": "spider_fang", "weight": 1, "min": 1, "max": 2},
                {"material": "cobweb", "weight": 3, "min": 1, "max": 2}]
        },
    ],
    "grounds": [
        {"key": "verdant_meadow", "name": "翠綠草原", "danger": 1, "min_legion_level": 1,
         "description": "一望無際的草原，高聳的草叢中隱藏著未知的危險。",
         "pool": [
             {"mob": "slime", "weight": 3}, 
             {"mob": "wild_boar", "weight": 2}, 
             {"mob": "wild_rabbit", "weight": 3}]},
        {"key": "whispering_forest", "name": "低語森林", "danger": 3, "min_legion_level": 2,
         "description": "樹木茂密的森林，彷彿傳來低語聲。",
         "pool": [{"mob": "wild_boar", "weight": 2}, 
                  {"mob": "grey_wolf", "weight": 3}, 
                  {"mob": "flame_lizard", "weight": 2},
                  {"mob": "flower_slime", "weight": 2}]},
        {"key": "mountain_pass", "name": "山脊小徑", "danger": 4, "min_legion_level": 3,
         "description": "崎嶇的山脊小徑，風聲呼嘯而過，隱藏著危險的生物。",
         "pool": [{"mob": "grey_wolf", "weight": 2}, 
                  {"mob": "dire_wolf", "weight": 1}, 
                  {"mob": "spider", "weight": 2},
                  {"mob": "flame_lizard", "weight": 2},
                  {"mob": "giant_flame_lizard", "weight": 1}]},
        {"key": "sunken_quarry", "name": "沉沒採石場", "danger": 5, "min_legion_level": 4,
         "description": "這裡曾經是個繁榮的採石場，但現在已經荒廢了。",
         "pool": [{"mob": "rock_slime", "weight": 2}, 
                  {"mob": "dire_wolf", "weight": 1}, 
                  {"mob": "stone_golem", "weight": 3},
                  {"mob": "dark_stone_golem", "weight": 1}]},
    ],
    "sites": [
        {"key": "old_mines", "name": "舊礦坑", "skill": "mine", "min_legion_level": 1,
         "description": "廢棄但是仍然有些許光線的礦坑。",
         "yields": [{"material": "iron_ore", "weight": 2, "min": 1, "max": 2},
                    {"material": "rough_stone", "weight": 3, "min": 1, "max": 3}]},
        {"key": "herb_garden", "name": "藥草園", "skill": "garden", "min_legion_level": 1,
         "description": "聞起來像雨水和泥土的氣息。",
         "yields": [{"material": "sunherb", "weight": 3, "min": 1, "max": 2},
                    {"material": "duskberry", "weight": 2, "min": 1, "max": 2}]},
        {"key": "deep_shafts", "name": "深井礦道", "skill": "mine", "min_legion_level": 3,
         "description": "深不見底的礦道，曾經是個老舊的井口。",
         "yields": [{"material": "iron_ore", "weight": 3, "min": 2, "max": 3},
                    {"material": "golem_core", "weight": 1, "min": 1, "max": 1}]},
        {"key": "ancient_ruins", "name": "古代遺跡", "skill": "garden", "min_legion_level": 3,
         "description": "古老的遺跡，似乎有些神秘的力量在其中。",
         "yields": [{"material": "thick_bark", "weight": 2, "min": 1, "max": 2},
                    {"material": "raspberry", "weight": 2, "min": 1, "max": 2},
                    {"material": "molt_skin", "weight": 1, "min": 1, "max": 1}]}
    ],
    "recipes": [
        {"key": "forge_iron_sword", "name": "鐵劍", 
         "weapon": "iron_sword", 
         "inputs": [{"material": "iron_ore", "qty": 5},
                    {"material": "boar_hide", "qty": 2}]},
        {"key": "forge_fang_dagger", "name": "狼牙短刀", 
         "weapon": "fang_dagger",
         "inputs": [{"material": "wolf_fang", "qty": 3},
                    {"material": "boar_hide", "qty": 1}]},
        {"key": "forge_old_staff", "name": "老舊法杖", 
         "weapon": "old_staff",
         "inputs": [{"material": "slime_goo", "qty": 3},
                    {"material": "boar_hide", "qty": 3}]},
        {"key": "forge_hunter_bow", "name": "獵弓", 
         "weapon": "hunter_bow",
         "inputs": [{"material": "wolf_fang", "qty": 3},
                    {"material": "wolf_hide", "qty": 1},
                    {"material": "sunherb", "qty": 1}]},
        {"key": "forge_golem_staff", "name": "魔像法杖", 
         "weapon": "golem_staff",
         "inputs": [{"material": "golem_core", "qty": 2},
                    {"material": "iron_ore", "qty": 5},
                    {"material": "rough_stone", "qty": 5}]},
        {"key": "forge_stone_shield", "name": "石盾", 
         "weapon": "stone_shield",
         "inputs": [{"material": "iron_ore", "qty": 5},
                    {"material": "golem_core", "qty": 1}]},
        {"key": "forge_blessed_gloves", "name": "祝福手套", 
         "weapon": "blessed_gloves",
         "inputs": [{"material": "molt_skin", "qty": 5},
                    {"material": "rabbit_foot", "qty": 2},
                    {"material": "golem_core", "qty": 2}]},
        {"key": "cook_hearty_stew", "name": "燉菜", "skill": "cook",
         "material": "hearty_stew", "qty": 2, "req": 0,
         "inputs": [{"material": "sunherb", "qty": 2},
                    {"material": "duskberry", "qty": 1}]},
        {"key": "cook_spring_roll", "name": "春捲", "skill": "cook",
         "material": "spring_roll", "qty": 2, "req": 1,
         "inputs": [{"material": "molt_skin", "qty": 1},
                    {"material": "sunherb", "qty": 3}]},
        {"key": "brew_bitter_tonic", "name": "苦藥水", "skill": "brew",
         "material": "bitter_tonic", "qty": 1, "req": 1,
         "inputs": [{"material": "rabbit_foot", "qty": 1},
                    {"material": "duskberry", "qty": 2}]},
        {"key": "brew_healing_potion", "name": "治癒藥水", "skill": "brew",
         "material": "healing_potion", "qty": 1, "req": 0,
         "inputs": [{"material": "duskberry", "qty": 5},
                    {"material": "slime_goo", "qty": 10}]},
        {"key": "forge_flame_lizard_staff", "name": "火蜥蜴法杖",
         "weapon": "flame_lizard_staff",
         "inputs": [{"material": "flame_lizard_core", "qty": 2},
                    {"material": "wolf_fang", "qty": 5},
                    {"material": "rabbit_foot", "qty": 2},
                    {"material": "iron_ore", "qty": 3}]},
        {"key": "forge_dark_stone_sword", "name": "黑石巨劍",
         "weapon": "dark_stone_sword",
         "inputs": [{"material": "dark_golem_core", "qty": 2},
                    {"material": "iron_ore", "qty": 5},
                    {"material": "rough_stone", "qty": 5},
                    {"material": "boar_hide", "qty": 1}]},
        {"key": "forge_sleeve_arrow", "name": "袖箭",
         "weapon": "sleeve_arrow",
         "inputs": [{"material": "spider_fang", "qty": 2},
                    {"material": "wolf_hide", "qty": 3},
                    {"material": "iron_ore", "qty": 1}]},
        {"key": "brew_rabbit_porridge", "name": "兔肉粥", "skill": "brew",
         "material": "rabbit_porridge", "qty": 1, "req": 2,
         "inputs": [{"material": "rabbit_foot", "qty": 1},
                    {"material": "sunherb", "qty": 2},
                    {"material": "cobweb", "qty": 1}]},
        {"key": "forge_flame_lizard_bow", "name": "火蜥弓",
         "weapon": "flame_lizard_bow",
         "inputs": [{"material": "flame_lizard_core", "qty": 2},
                    {"material": "spider_fang", "qty": 4},
                    {"material": "thick_bark", "qty": 4},
                    {"material": "cobweb", "qty": 2}]},
        {"key": "brew_red_potion", "name": "紅藥水", "skill": "brew",
         "material": "red_potion", "qty": 1, "req": 2,
         "inputs": [{"material": "cobweb", "qty": 3},
                    {"material": "raspberry", "qty": 2},
                    {"material": "slime_goo", "qty": 5}]},
    ],
    "upgrade_costs": [
        {"level": 2, "material": "slime_goo", "base_qty": 5},
        {"level": 2, "material": "boar_hide", "base_qty": 3},
        {"level": 3, "material": "wolf_fang", "base_qty": 5},
        {"level": 3, "material": "rough_stone", "base_qty": 10},
        {"level": 3, "material": "rabbit_foot", "base_qty": 3},
        {"level": 4, "material": "thick_bark", "base_qty": 5},
        {"level": 4, "material": "flame_lizard_core", "base_qty": 4},
        {"level": 4, "material": "golem_core", "base_qty": 10},
        #{"level": 5, "material": "dark_golem_core", "base_qty": 5},
        #{"level": 5, "material": "spider_fang", "base_qty": 6},
        #{"level": 5, "material": "molt_skin", "base_qty": 10},
    ],
    # Daily supply (once/day button on /legion). Grouped by contribution
    # threshold like upgrade_costs are by level: a player receives EVERY entry
    # at the HIGHEST threshold their contribution reaches -- not cumulative.
    "daily_reward": [
        {"threshold": 10, "material": "bitter_tonic", "qty": 1},
        {"threshold": 10, "material": "hearty_stew", "qty": 1},
        {"threshold": 50, "material": "bitter_tonic", "qty": 1},
        {"threshold": 50, "material": "hearty_stew", "qty": 2},
        {"threshold": 100, "material": "bitter_tonic", "qty": 2},
        {"threshold": 100, "material": "spring_roll", "qty": 1},
    ],
}
