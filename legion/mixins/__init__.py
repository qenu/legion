"""LegionCog mixins: one domain per module, assembled by cog.py.

Each mixin inherits ``LegionCogBase`` (the shared attribute surface, gates,
and interceptors) and contributes its slash/text commands plus the service
methods its views call back into. discord.py's CogMeta walks the MRO, so
commands defined here are collected exactly as if they lived on LegionCog.
"""

from maki.cogs.legion.mixins.admin import AdminMixin
from maki.cogs.legion.mixins.base import FREEZE_FLAG_KEY, LegionCogBase
from maki.cogs.legion.mixins.craft import CraftMixin
from maki.cogs.legion.mixins.expedition import ExpeditionMixin, _CaptchaState
from maki.cogs.legion.mixins.gather import GatherMixin
from maki.cogs.legion.mixins.legion_panel import LegionPanelMixin
from maki.cogs.legion.mixins.profile import ProfileMixin

__all__ = (
    "AdminMixin",
    "CraftMixin",
    "ExpeditionMixin",
    "FREEZE_FLAG_KEY",
    "GatherMixin",
    "LegionCogBase",
    "LegionPanelMixin",
    "ProfileMixin",
    "_CaptchaState",
)
