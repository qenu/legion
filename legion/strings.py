"""All user-facing text for the legion cog lives here (single point for
copy edits and future localization)."""

# --- defaults / naming ---
DEFAULT_PLAYER_NAME = "冒險者"
DEFAULT_LEGION_NAME = "無名兵團"
PLAYER_REFER = "冒險者"
LEGION_REFER = "兵團"
LEGION_DNE = "無所屬兵團"
PLAYER_UNIT = "人"
LEVEL_UNIT = "等級"
EXPERIENCE_UNIT = "經驗值"
EXPERIENCE_UNIT_SHORT = "經驗"
EXPERIENCE_UNIT_SHORTER = "exp"
SKILL_REFER = "技能"

# --- commands ---
PROFILE_COMMAND_NAME = "account_個人資料"
EXPEDITION_COMMAND_NAME = "expedition_遠征"
LEGION_COMMAND_NAME = "legion_兵團"
CRAFTING_COMMAND_NAME = "make_製作"
GATHERER_COMMAND_NAME = "resource_採集"

PROFILE_COMMAND_DESC = "查看個人資料、背包與精通能力"
EXPEDITION_COMMAND_DESC = "發起遠征，狩獵怪物"
LEGION_COMMAND_DESC = "查看兵團資訊"
CRAFTING_COMMAND_DESC = "製作武器、料理與藥水"
GATHERER_COMMAND_DESC = "前往採集材料"

# --- onboarding ---
ONBOARD_PROMPT = "你即將加入 **{legion}** — 選擇一把武器，與你的同伴並肩作戰！"
ONBOARD_WELCOME = "歡迎加入 **{legion}**，{player}！你的 **{weapon}** 已準備就緒。"
ONBOARD_ANY_CMD = "你可以使用 `/expedition` 發起遠征，或使用 `/resource` 前往採集材料。"
ONBOARD_DM_ONLY = "你必須在伺服器中使用此指令。"

# --- legion ---
LEGION_NOT_CONFIGURED = "兵團尚未成立，需要一位管理員先運行設置並選擇一個頻道。"
LEGION_UPGRADE_READY = "**{legion}** 已經完成升級至等級 {level} 的條件！"
LEGION_UPGRADE_READY_SHORT = "兵團已經完成升級條件！"
LEGION_UPGRADE_DONE = "**{legion}** 已經升級至等級 {level}！"
LEGION_UPGRADE_SHORT = "尚未累積足夠的經驗值或材料進行升級。"
LEGION_UPGRADE_MAXED = "兵團已達目前最高等級，暫無更高的升級。"
DAILY_SUPPLY_TITLE = "每日補給"
DAILY_SUPPLY_RECEIVED = "領取了每日補給：{mats}。"
DAILY_SUPPLY_CLAIMED = "你今天已經領取過每日補給了，明天再來吧。"
DAILY_SUPPLY_LOW = "貢獻值不足，至少需要 {need:,} 點才能領取每日補給。"
DAILY_SUPPLY_NONE = "目前沒有可領取的每日補給。"
LEGION_DONATED = "捐贈了 {material}×{qty:,} (獲得 {contri:,} 貢獻值)。"
LEGION_DONATED_CAPPED = (
    "捐贈了 {material}×{qty:,} (獲得 {contri:,} 貢獻值)；倉庫已滿，其餘已保留。"
)
LEGION_STOCKPILE_FULL = "倉庫的 {material} 已達上限，無法再捐贈。"
LEGION_DONATE_SHORT = "{material} 數量不足。"
LEGION_DONATE_NOT_NEEDED = "{material} 不是升級所需材料，無法捐贈。"
MEMBERS_TITLE = "成員"
MEMBERS_NAME_COL = "玩家名稱"
MANAGER_TITLE = "管理員"
LEGION_LEADERBOARD = "排行榜"
LEGION_CONTRIBUTION = "貢獻值"
LEGION_KILLS_COUNT = "擊殺數"
LEGION_SET_CHANNEL = "設定文字頻道..."
LEGION_SET_MANAGER = "設定管理員..."
LEGION_NO_CHANNEL_SET = "尚未設定文字頻道，無法進行遠征或採集。"
DONATE_TITLE = "捐贈"
DONATE_DESC = "捐贈材料至倉庫，換取貢獻值（稀有度×數量）。"
DONATE_PICK = "選擇要捐贈的材料..."
LEGION_UPDATE_SHEET = "升級需求"
DONATE_NEEDED_TAG = "升級需求 {have:,}/{need:,}"
DONATE_QTY_LABEL = "捐贈數量"
DONATE_QTY_PLACEHOLDER = "1 ~ {max:,}"
DONATE_INVALID_QTY = "數量無效。"
DONATE_NOTHING = "你沒有任何材料可以捐贈。"
DONATE_MEMBERS_ONLY = "只有成員可以捐贈。"
DONATE_ANNOUNCE_TITLE = "📦 倉庫捐獻"
DONATE_ANNOUNCE_DESC = "**{donor}** 捐贈了 **{material}** ×{qty:,}！"
DONATE_ANNOUNCE_PROGRESS = "目前庫存：**{have:,} / {need:,}**（升級需求）"
DONATE_ANNOUNCE_STOCK = "目前庫存：**{have:,}**"
LEGION_SETTINGS_TITLE = "設定"
LEGION_SETTINGS_NAME = "名稱"
LEGION_SETTINGS_CHANNEL = "頻道"
LEGION_SETTINGS_NOT_SET = "未設定"
LEGION_RENAME_PROMPT = "輸入新的兵團名稱"
LEGION_RENAMED = "名稱已變更為 **{name}**。"
LEGION_CHANNEL_SET = "頻道已設定為 {channel}。"
LEGION_MANAGER_SET = "已任命 **{player}** 為管理員。"
LEGION_OFFICERS_ONLY = "只有管理員可以進行此操作。"
LEGION_ALREADY_MEMBER = "你已經是兵團成員了。"
LEGION_NOT_MEMBER = "你不是兵團成員，無法進行此操作。"
LEGION_WELCOME = "歡迎加入 **{legion}**！"
LEGION_LEFT = "你已離開 **{legion}**。"

# --- hunting ---
HUNTING_TITLE = "狩獵"
HUNTING_RANDOM_DESC = "隨機地區，獲得額外的精通點數與掉落物品。"
HUNTING_EXPEDITION_IN_PROGRESS = "遠征進行中"
HUNTING_EXPEDITION_DESC_LIST = [
    (
        "你即將前往 **{ground}** 進行遠征，\n"
        "這裡有一隻 **{mob}** (等級 {tier}) 正在徘徊！"
    ),
    ("即將前往 **{ground}** 進行遠征，對抗 **{mob}** (等級 {tier}) ..."),
    ("發現 **{mob}** (等級 {tier}) 正在 **{ground}** 徘徊，"),
]
HUNTING_EXPEDITION_GROUP_DESC_LIST = [
    (
        "你即將前往 **{ground}** 進行遠征，\n"
        "這裡有一隻 **{mob}** (等級 {tier}) 以及其他怪物在附近！\n"
    ),
    ("即將前往 **{ground}** 進行遠征，對抗 **{mob}** (等級 {tier}) 以及其他怪物 ..."),
    ("發現 **{mob}** (等級 {tier}) 正在 **{ground}** 徘徊，還有其他怪物在附近！"),
]
HUNTING_EXPEDITION_ROUNDSLIMIT = "你必須在 **{rounds} 回合** 內擊敗它"
HUNTING_EXPEDITION_TIMELEFT = "準備階段剩餘時間：<t:{expires}:R>"
HUNTING_PREPARATION_OVER = "準備階段已結束"
COMBAT_LOG_BUTTON = "戰鬥紀錄"
COMBAT_LOG_FIELD = "第 {round_no} 回合"
HUNTING_EXPEDITION_BUSY = "你目前正在 **{ground}** 進行遠征，無法進行其他操作。"
HUNTING_EXPEDITION_BUSY_SHORT = "目前正在進行遠征，無法進行該操作。"
HUNTING_PARTY = "參與者"
HUNTING_PARTY_EMPTY = "目前沒有任何人參與遠征。"
HUNTING_FAILED_INIT = "遠征失效"
HUNTING_PARTY_MIA = "沒有人參與遠征。"
EXPEDITION_INIT = "於 {channel} 發起了遠征!"
EXPEDITION_RANDOM_TITLE = "隨機遠征"
EXPEDITION_START_TITLE = "發起遠征"
HUNTING_GROUND_LIST_TITLE = "狩獵地區"
HUNTING_GROUND_MOBS_TITLE = "可能出現的怪物"
HUNTING_GROUND_DROPS_TITLE = "可能的掉落物"
HUNTING_GROUND_NO_INTEL = "尚無情報。"
HUNTING_GROUND_MOB_LINE = "**{name}** (T{tier}) — {pct}%"
HUNTING_FOOTER_TOOLTIP = "使用 [/{command}] 來發起遠征。"

CAPTCHA_PROMPT = "🤖 驗證：請點擊數字 **{answer}**"
CAPTCHA_FAILED = "❌ 驗證失敗，暫時無法發起遠征。<t:{until}:R> 後再試。"
CAPTCHA_LOCKED = "⏳ 驗證失敗鎖定中，<t:{until}:R> 後再試。"
CAPTCHA_BLACKLISTED = "🚫 你已因多次驗證失敗被暫時封鎖，無法發起遠征。"

HUNTING_GROUND_GONE = "找不到指定的狩獵地區。"
HUNTING_MOB_GONE = "找不到指定的怪物。"
HUNTING_EXPEDITION_OVER = "遠征已結束。"

# --- gathering ---
GATHER_TITLE = "採集"
GATHER_BUSY_TITLE = "在 {site} 採集中..."
GATHER_BLOCKED = "你目前還在 **{site}** 採集中，無法進行其他操作。"
GATHER_BLOCKED_SHORT = "你目前還在採集中，無法進行其他操作。"
GATHER_STARTED = "即將前往 **{site}** ..."
GATHER_STOPPED = "從 **{site}** 回來，歷時 {hours} 小時 {minutes} 分鐘。"
GATHER_RESULT = "獲得了 {loot} (精通 +{pts:,})"
GATHER_RESULT_EMPTY = "沒有任何收穫"
GATHER_NOTHING = "你沒有在任何地方採集。"
GATHER_DESCRIPTION = "前往指定地點採集材料，獲得精通點數與材料。"
GATHER_YIELDS = "可採集材料"
GATHER_SKILL_TYPES = {
    "mine": "採礦",
    "garden": "種植",
}
GATHER_AFK_SINCE = "放置開始於"
GATHER_NO_SUCH_SITE = "找不到指定的採集地點。"

# --- combat ---
COMBAT_EVENT = {
    "skill": "**{actor}** 對 **{target}** 使用 __{detail}__ 造成 **{value:,}** 點傷害",
    "attack": "**{actor}** 攻擊了 **{target}** 造成 **{value:,}** 點傷害",
    "heal": "**{actor}** 使用 __{detail}__ 治療了 **{target}** ，恢復 **{value:,}** 點生命值",
    "stun": "**{actor}** 對 **{target}** 使用 __{detail}__ 造成了眩暈",
    "stunned": "**{actor}** 眩暈中，無法行動！",
    "bleed": "**{actor}** 對 **{target}** 使用 __{detail}__ 造成流血",
    "bleed_tick": "**{actor}** 受到了 **{value:,}** 點流血傷害",
    "poison": "**{actor}** 對 **{target}** 使用 __{detail}__ 造成中毒",
    "poison_tick": "**{actor}** 受到了 **{value:,}** 點中毒傷害",
    "poison_effect": "**{actor}** 毒性擴散，額外承受了 **{value:,}** 點傷害",
    "burn": "**{actor}** 對 **{target}** 使用 __{detail}__ 造成燃燒",
    "burn_tick": "**{actor}** 受到了 **{value:,}** 點燃燒傷害",
    "burn_effect": "**{actor}** 遭到灼傷，額外承受了 **{value:,}** 點傷害",
    "freeze": "**{actor}** 對 **{target}** 使用 __{detail}__ 造成了冰凍",
    "freeze_tick": "**{actor}** 受到了 **{value:,}** 點冰凍傷害",
    "freeze_effect": "**{actor}** 遭到冰凍，無法行動！",
    "death": "**{actor}** 倒下了!",
    "passive": "**{actor}** 的 __{detail}__ 發動了！",
    "shield_applied": "**{actor}** 使用 __{detail}__ 施加了護盾，獲得了 **{value:,}** 點護盾值",
}
COMBAT_ROUND = "戰鬥紀錄 第 {round_no} / {rounds_limit} 回合"
COMBAT_ROUND_EMPTY = "沒有任何事件發生。"

# --- settlement log ---
SETTLE_OUTSIDER_TAG = "不在從屬的兵團中"
SETTLE_MASTERY_NET = "{category}精通 {delta}"  # delta pre-signed, e.g. "+6" / "−5"
SETTLE_RELOCK_LINE = " ({category}精通下降 {levels:,} 級)"
SETTLE_HEAL_DONE = "治療量"
SETTLE_DIED = "陣亡"
SETTLE_DAILY_CONTRI = "貢獻值 +{pts:,}"
SETTLE_WON = "成功擊敗了 **{mob}** ({rounds} 回合)"
SETTLE_END = "**{mob}** 回合耗盡離開了 ({rounds} 回合)"
SETTLE_LOST = "**{mob}** 擊敗了所有的冒險者 ({rounds} 回合)"
SETTLE_DROP = "獲得了物品"
SETTLE_PAGE = "第 {page}/{pages} 頁"
SETTLE_MY_RESULT = "我的結算"
SETTLE_MY_RESULT_NONE = "你沒有參與這場戰鬥。"
SETTLE_DAMAGE_DEALT = "造成傷害"
SETTLE_DAMAGE_TAKEN = "承受傷害"
SETTLE_RESULT_AUTHOR = "遠征結算"
SETTLE_MOB_HP = "{mob} ({hp:,}/{max_hp:,})"

# --- profile ---
PROFILE_CHANGE_NICK = "變更暱稱"
PROFILE_CHANGE_NICK_PROMPT = "輸入新的暱稱"
PROFILE_NEW_NICK = "暱稱已變更為 **{nickname}**。"
PROFILE_MASTERY = "精通"
PROFILE_TITLE = "個人資料"

# --- inventory ---
INVENTORY_TITLE = "物品欄"
INVENTORY_EQUIPPED = "已裝備"
INVENTORY_MAIN = "主手裝備"
INVENTORY_SUB = "副手裝備"
INVENTORY_CHOOSE = "選擇道具"
INVENTORY_USE = "使用/裝備"
EQUIP_TITLE = "裝備"
INVENTORY_DISMANTLE = "拆解"
INVENTORY_WEAPON_NAME = "{quality} {weapon}"
INVENTORY_CONSUMABLE_NAME = "{material}×{qty:,}"
INVENTORY_CONSUMABLE_DESC = "消耗品"
INVENTORY_MATERIALS_TITLE = "材料"
INVENTORY_WEAPONS_TITLE = "武器"
INVENTORY_EQUIPPED_TITLE = "已裝備"
INVENTORY_CATEGORY_PICK = "查看武器或消耗品..."
INVENTORY_CATEGORY_WEAPONS_DESC = "所有持有的武器"
INVENTORY_CATEGORY_CONSUMABLES_DESC = "所有持有的消耗品"
INVENTORY_EMPTY = "無"
INVENTORY_POTENTIAL = "潛能 {pct}%"
INVENTORY_HEAL_EFFECT = "恢復 {value:,} 點生命值"
INVENTORY_USED = "使用了 **{material}**，恢復 {healed:,} 點生命值 ({hp:,}/{max_hp:,})。"
INVENTORY_DISMANTLED = "拆解了 **{weapon}**。"
INVENTORY_DISMANTLE_RETURNED = "回收了 {mats}。"
INVENTORY_DISMANTLE_CONFIRM = (
    "確定要拆解 **{weapon}** 嗎？此操作無法復原，回收材料並非必定。"
)
INVENTORY_DISMANTLE_CANCELLED = "已取消拆解。"
INVENTORY_REGEN_EFFECT = "每分鐘恢復 {value:,} 點生命值，持續 {duration} 分鐘"
POTION_REVIVE_TAG = "可於陣亡時使用"
FOOD_BUFF_TITLE = "食物效果"
FOOD_BUFF_ACTIVE = "每分鐘額外恢復 {value:,} 點生命值，<t:{until}:R> 結束。"
FOOD_STAT_BUFF_ACTIVE = "{category} +{value:,}，<t:{until}:R> 結束。"
FOOD_BUFF_APPLIED = (
    "食用了 **{material}**，每分鐘恢復 {value:,} 點生命值，持續 {duration} 分鐘。"
)
FOOD_BUFF_EFFECT = "增加 {value:,} {category} ，持續 {duration} 分鐘"
FOOD_BUFF_EFFECT_APPLIED = (
    "食用了 **{material}**，增加 {value:,} {category} ，持續 {duration} 分鐘。"
)
# Display names for the {category} slot in the stat-buff strings above.
STAT_NAMES = {
    "atk": "攻擊力",
    "def": "防禦力",
    "speed": "速度",
    "hp": "生命值",
    "taunt": "嘲諷",
    "regen": "生命回復",
    "bleed_res": "流血抗性",
    "poison_res": "中毒抗性",
    "fire_res": "火焰抗性",
    "cold_res": "寒冷抗性",
}
DEATH_TIMER_TITLE = "死亡回歸"
DEATH_TIMER_VALUE = "<t:{revive}:R> 復活"
REVIVED = "使用了 **{material}** 成功復活！恢復 {healed:,} 點生命值。"
DEAD_BLOCKED = "你已陣亡，無法進行此操作。使用藥水即可復活。"

INVENTORY_DISMANTLE_WEAPON_ONLY = "你只能拆解武器。"
INVENTORY_CANNOT_DISMANTLE = "你無法拆解這個物品。"
INVENTORY_CANNOT_DISMANTLE_EQUIPPED = "你無法拆解已裝備的武器。"
INVENTORY_QTY_NOT_ENOUGH = "你沒有足夠的數量。"

# --- use item on others (context menu) ---
USE_ITEM_CONTEXT_NAME = "使用道具"
USE_ITEM_PICK = "選擇要對 **{target}** 使用的道具："
USE_ITEM_TARGET_NOT_PLAYER = "對方還不是冒險者。"
USE_ITEM_NONE = "你沒有可以使用的消耗品。"
USE_ITEM_TARGET_DEAD_FOOD = "**{target}** 已陣亡，無法進食。先用藥水救活他吧。"
USE_ITEM_MASTERY_GAP = "**{target}** 的歷練與你相差過大，無法對其使用道具。"
USE_ITEM_ANNOUNCE = "**{player}** 對 **{target}** 使用了 **{material}**，{result}"
USE_ITEM_SHORT_NOTE = "對 **{target}** 使用了 **{material}**。"
INVENTORY_USED_OTHER = (
    "對 **{target}** 使用了 **{material}**，恢復 {healed:,} 點生命值。"
)
REVIVED_OTHER = (
    "**{material}** 將 **{target}** 從鬼門關拉了回來，恢復 {healed:,} 點生命值！"
)
FOOD_BUFF_APPLIED_OTHER = "餵 **{target}** 吃下了 **{material}**，每分鐘恢復 {value:,} 點生命值，持續 {duration} 分鐘。"
FOOD_BUFF_EFFECT_APPLIED_OTHER = "餵 **{target}** 吃下了 **{material}**，增加 {value:,} {category} ，持續 {duration} 分鐘。"
HP_TOO_LOW = "生命值低於 {pct}%，無法參加遠征。"
MATERIAL_KIND_NAMES = {
    "material": "材料",
    "food": "食物",
    "potion": "藥水",
    "consumable": "消耗品",
    "chest": "寶箱",
}

# --- showoff profile (context menu) ---
CHECK_PROFILE_CONTEXT_NAME = "查看個人資料"
PROFILE_TARGET_NOT_PLAYER = "對方還不是冒險者。"
MASTERY_SUMMARY = "{category}精通 Lv.{level}"
SHOWOFF_PROFILE_TITLE = "{name} 的個人資料"
SHOWOFF_PROFILE_FOOTER = "來自 {author} 的公開請求。"

# --- crafting ---
CRAFT_SHORT_MATS = "缺少材料 (**{recipe}**)"
CRAFT_RESULT = "鍛造了 {quality} **{weapon}**！"
CRAFT_TITLE = "製作工坊"
CRAFT_HOME_DESC = "選擇一個技能開始製作。"
FORGE_TITLE = "鍛造"
COOK_TITLE = "烹飪"
BREW_TITLE = "釀造"
CRAFT_PICK = "製作什麼？"
CRAFT_MADE = "製作了 **{material}**×{qty:,} ！"
# Craft mastery perk landed: the roll doubled the output.
CRAFT_MADE_DOUBLE = "製作了 **{material}**×{qty:,} ！✨ 手感絕佳，產量翻倍了！"
CRAFT_MAT_DETAIL = "{name}×{count:,}"
CRAFT_NOTHING = "這個配方什麼都做不出來…"
CRAFT_NEED_MASTERY = "需要 {skill} 熟練度 Lv{req} 以上"
CRAFT_MASTERY_TAG = "Lv.{level}"
LIFE_SKILL_NAMES = {
    "mine": "採礦",
    "garden": "園藝",
    "cook": "烹飪",
    "brew": "釀造",
    "forge": "鍛造",  # technically not a life skill, but it's in the same menu
}
FORGE_EMOJI = "⚒️"
COOK_EMOJI = "🍲"
BREW_EMOJI = "🧪"
WEAPON_QUALITY_NAMES = {
    "crude": "殘破的",
    "standard": "",
    "fine": "精良的",
    "masterwork": "非凡的",
    "unique": "獨特的",
    "legendary": "傳說的",
    "mythic": "神話的",
}
WEAPON_HAND_NAMES = {"main": INVENTORY_MAIN, "sub": INVENTORY_SUB}
CRAFT_DESC = {
    "forge": "使用材料製作武器。",
    "cook": "使用食材製作料理。",
    "brew": "使用草藥製作藥水。",
}
CRAFT_NO_SUCH_RECIPE = "找不到指定的配方。"

# --- patching ---
PATCH_TITLE = "版本更新"
PATCH_BLOCKED = "🔧 即將進行版本更新，功能暫時關閉中"
LEGION_FROZEN = "🧊 系統維護中，功能暫時關閉，請稍後再試。"
PATCH_UP_TO_DATE = "✅ 目前已是最新版本。"
PATCH_UPDATE_FOUND = "🆕 有新的更新可用，查看下方更新內容。"
PATCH_SCHEDULED = (
    "🗓️ 更新已排程：遊戲功能鎖定時間 <t:{lock}:R>，更新生效時間 <t:{apply}:R>。"
)
PATCH_CANCELLED = "已取消排程更新，所有功能已解鎖。"
PATCH_APPLIED = "✅ Patch **{version}** (`{hash}`) 已應用，新增行 {created}。"
PATCH_FORCE_CONFIRM = "⚠️ 強制更新將 **立即生效**，跳過鎖定時間。正在進行中的玩家將不會收到警告。是否繼續？"
PATCH_CURRENT = "目前版本"
PATCH_NOTES = "更新內容"
PATCH_LIVE_CONTENT = "運行中內容"
PATCH_ON_DISK = "磁碟版本"
PATCH_CHECK = "檢查更新"
PATCH_VIEW_UPDATE = "確認更新"
PATCH_UPDATE = "更新"
PATCH_FORCE_UPDATE = "強制更新"
PATCH_THIS_LEGION = "現行兵團"

# --- mastery ---
MASTERY_TITLE = "能力精通"
MASTERY_TITLE_SHORT = "精通"
MASTERY_WEAPON = "武器掌握精通"
MASTERY_LIFE = "生活技能精通"
MASTERY_NONE = "尚未精通任何技能"
MASTERY_FOOTER = "超過 Lv.{softcap} 的精通點數為零和區域 · 精通上限 Lv.{hardcap}"

# --- skills ---
SKILL_ACTIVE_SKILL = "主動技能"
SKILL_PASSIVE_SKILL = "被動技能"
SKILL_COOLDOWN_DESCRIPTION = "冷卻時間 {value:,} 回合。"
SKILL_ACTIVE_DESCRIPTION = {
    "damage": "對目標造成 {value:,} 點傷害，",
    "fire_damage": "對目標造成 {value:,} 點火焰傷害 (受火焰抗性影響)，",
    "cold_damage": "對目標造成 {value:,} 點寒冷傷害 (受寒冷抗性影響)，",
    "heal": "對目標恢復 {value:,} 點生命值，",
    "stun": "對目標造成眩暈，持續 {value:,} 回合，",
    "bleed": "對目標造成流血，每回合造成 {value:,} 點傷害，",
    "poison": "對目標造成中毒，每回合造成 {value:,} 點傷害，",
    "burn": "對目標造成燃燒，每回合造成 {value:,} 點傷害，",
    "freeze": "對目標造成冰凍，每回合造成 {value:,} 點傷害，",
    "shield": "對自己施加 {value:,} 點的護盾，",
}
SKILL_PASSIVE_DESCRIPTION = {
    "hp": "生命值 +{value:,}",
    "atk": "攻擊力 +{value:,}",
    "def": "防禦力 +{value:,}",
    "speed": "速度 +{value:,}",
    "taunt": "嘲諷 +{value:,}",
    "regen": "每分鐘恢復 {value:,} 點生命值",
    # {value:+,} keeps the sign honest: +3 = 抗性, -5 = 弱點 (額外受傷).
    # fire_res covers 燃燒 DoT + 火焰傷害; cold_res covers 冰凍 DoT + 寒冷傷害.
    "bleed_res": "流血抗性 {value:+,}",
    "poison_res": "中毒抗性 {value:+,}",
    "fire_res": "火焰抗性 {value:+,}",
    "cold_res": "寒冷抗性 {value:+,}",
}
SKILL_TIER_TAG = "T{tier}"
SKILL_LOCKED_TAG = "<:lock:1526099265636667543> 需要{category}精通 Lv{req} 解鎖"

# --- craft detail / confirm flow ---
CRAFT_ACTION = "製作"
CRAFT_CONFIRM = "確定要製作 **{item}** 嗎？"
CRAFT_CRAFTING = "正在製作 **{item}**"
CRAFT_CANCELLED = "已取消。"
CRAFT_MATS_TITLE = "所需材料"
CRAFT_MAT_LINE = "{mark} {name} {have:,}/{need:,}"
CRAFT_POTENTIAL_RANGE = "潛能範圍 {low}% ~ {high}%"
CRAFT_RESULT_QTY = "產出 {qty:,} 個"
# Easter egg: the crafting animation's dot count quietly telegraphs the
# rolled quality before the reveal. Shh.
QUALITY_DOTS = {"crude": 2, "standard": 3, "fine": 4, "masterwork": 5}
WEAPON_QUALITY_TITLE = "品質"
WEAPON_QUALITY_DISPLAY = {
    "crude": "殘破",
    "standard": "普通",
    "fine": "精良",
    "masterwork": "非凡",
    "unique": "獨特",
    "legendary": "傳說",
    "mythic": "神話",
}


# --- misc ---
RANDOM_PREFIX = "隨機"
AREA_TITLE = "地區"
CHOOSE_TITLE = "選擇"
JOIN_TITLE = "加入"
LEAVE_TITLE = "離開"
DANGER_TITLE = "危險"
EXPONENT_TITLE = "指數"
UPGRADE_TITLE = "升級"
CANCEL_TITLE = "取消"
CONFIRM_TITLE = "確認"
PICK_DESTINATION_TITLE = "選擇地點"
RETURN_TITLE = "<< 返回"
HEALTHPOINT_TITLE_SHORT = "HP"
HEALTHPOINT_TITLE = "生命值"
GAINED_TITLE = "獲得"
INCREASED_TITLE = "增加"
DECREASED_TITLE = "減少"
NOT_EQUIPPED_TITLE = "-"
DNE_TITLE = "不存在"
PAGE_NUM_TITLE = "第 {page}/{pages} 頁"
MATERIAL_TITLE = "材料"
INFO_TITLE = "資訊"
BELONGS_TO_TITLE = "所屬"
QUESTION_TITLE = "???"
MYSELF_TITLE = "自己"

# --- emoji ---
BATTLE_EMOJI = "<:battle:1526099270984405083>"
UP_EMOJI = "<:arrowup:1526099267348074616>"
CHECK_EMOJI = "<:greenTick:1408101518074187786>"
CROSS_EMOJI = "<:redTick:1408101524118306996>"
ARROW_LEFT_EMOJI = "←"
ARROW_RIGHT_EMOJI = "→"
SKULL_EMOJI = "<:skull:1526099261119270933>"
LOCK_EMOJI = "<:lock:1526099265636667543>"
COG_EMOJI = "<:cogwheel:1526099268694315130>"
CROWN_EMOJI = "<:crown:1526066739727827135>"
TIMES_EMOJI = "×"
ADDITION_EMOJI = "+"
LEVEL_EMOJI = "Lv."
MAX_EMOJI = "MAX"

# --- bars ---
HEAD_EMPTY = "<:head_empty:1524237769637892309>"
HEAD_HALF_FULL = "<:head_half_full:1524237774008356985>"
HEAD_FULL = "<:head_full:1524237771722588302>"
BODY_EMPTY = "<:body_empty:1524237763463872543>"
BODY_HALF_FULL = "<:body_half_full:1524237767725285578>"
BODY_FULL = "<:body_full:1524237765624070384>"
TAIL_EMPTY = "<:tail_empty:1524237776155967518>"
TAIL_HALF_FULL = "<:tail_half_full:1524237782258552932>"
TAIL_FULL = "<:tail_full:1524237777892413571>"
