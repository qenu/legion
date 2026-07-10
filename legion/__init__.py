from typing import TYPE_CHECKING

from loguru import logger as log

if TYPE_CHECKING:
    from maki.core import Maki

# NOTE: keep this module import-light. Tortoise imports
# `maki.cogs.legion.model.model` at init, which executes this package
# __init__ -- a top-level `from maki.core import ...` here would drag the
# whole bot core into every model import.


async def setup(bot: "Maki") -> None:
    from maki.cogs.legion.cog import LegionCog

    await bot.add_cog(LegionCog(bot))
    log.info("Legion cog loaded successfully.")
