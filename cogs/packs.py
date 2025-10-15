"""
DeckForge Pack Commands Cog
Handles pack inventory, claiming, and trading commands
"""
import discord
from discord.ext import commands
import asyncpg
import uuid
from datetime import datetime, timezone
from typing import Optional

from utils.card_helpers import (
    check_drop_cooldown,
    format_cooldown_time,
    RARITY_HIERARCHY
)
from utils.pack_logic import (
    PACK_TYPES,
    MAX_TOTAL_PACKS,
    validate_pack_type,
    format_pack_type
)


class PackCommands(commands.Cog):
    """Cog for pack inventory and management commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_pool: asyncpg.Pool = bot.db_pool
        self.admin_ids = bot.admin_ids
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        return user_id in self.admin_ids or user_id == self.bot.owner_id
    
    async def get_total_packs(self, conn, user_id: int) -> int:
        """Get total number of packs a user owns"""
        result = await conn.fetchval(
            "SELECT COALESCE(SUM(quantity), 0) FROM user_packs WHERE user_id = $1",
            user_id
        )
        return result or 0
    
    async def get_pack_quantity(self, conn, user_id: int, pack_type: str) -> int:
        """Get quantity of a specific pack type for a user"""
        result = await conn.fetchval(
            "SELECT quantity FROM user_packs WHERE user_id = $1 AND pack_type = $2",
            user_id, pack_type
        )
        return result or 0
    
    async def add_packs(self, conn, user_id: int, pack_type: str, quantity: int) -> bool:
        """Add packs to user inventory. Returns False if would exceed max."""
        # Check current total
        total_packs = await self.get_total_packs(conn, user_id)
        
        if total_packs + quantity > MAX_TOTAL_PACKS:
            return False
        
        # Upsert pack quantity
        await conn.execute(
            """INSERT INTO user_packs (user_id, pack_type, quantity)
               VALUES ($1, $2, $3)
               ON CONFLICT (user_id, pack_type)
               DO UPDATE SET quantity = user_packs.quantity + $3""",
            user_id, pack_type, quantity
        )
        return True
    
    async def remove_packs(self, conn, user_id: int, pack_type: str, quantity: int) -> bool:
        """Remove packs from user inventory. Returns False if insufficient packs."""
        current_qty = await self.get_pack_quantity(conn, user_id, pack_type)
        
        if current_qty < quantity:
            return False
        
        new_qty = current_qty - quantity
        
        if new_qty == 0:
            # Delete row if quantity reaches 0
            await conn.execute(
                "DELETE FROM user_packs WHERE user_id = $1 AND pack_type = $2",
                user_id, pack_type
            )
        else:
            # Update quantity
            await conn.execute(
                "UPDATE user_packs SET quantity = $3 WHERE user_id = $1 AND pack_type = $2",
                user_id, pack_type, new_qty
            )
        
        return True
    
    @commands.command(name='claimfreepack')
    async def claim_free_pack(self, ctx):
        """
        Claim 1 free Normal Pack every 8 hours.
        Usage: !claimfreepack
        """
        user_id = ctx.author.id
        
        async with self.db_pool.acquire() as conn:
            # Get or create player record
            player = await conn.fetchrow(
                "SELECT user_id, last_drop_ts FROM players WHERE user_id = $1",
                user_id
            )
            
            if not player:
                # Create new player
                await conn.execute(
                    "INSERT INTO players (user_id, credits, last_drop_ts) VALUES ($1, 0, NULL)",
                    user_id
                )
                last_drop_ts = None
            else:
                last_drop_ts = player['last_drop_ts']
            
            # Check cooldown (reusing the same cooldown system)
            can_claim, time_remaining = check_drop_cooldown(last_drop_ts)
            
            if not can_claim and time_remaining:
                cooldown_str = format_cooldown_time(time_remaining)
                await ctx.send(f"⏰ You can claim a free pack again in **{cooldown_str}**!")
                return
            
            # Check pack cap
            total_packs = await self.get_total_packs(conn, user_id)
            
            if total_packs >= MAX_TOTAL_PACKS:
                await ctx.send(
                    f"❌ You've reached the maximum pack limit of **{MAX_TOTAL_PACKS}** packs!\n"
                    f"Open some packs with `!drop` to make room."
                )
                return
            
            # Add 1 Normal Pack
            success = await self.add_packs(conn, user_id, 'Normal Pack', 1)
            
            if not success:
                await ctx.send(f"❌ Cannot claim pack - you would exceed the {MAX_TOTAL_PACKS} pack limit!")
                return
            
            # Update last claim timestamp
            await conn.execute(
                "UPDATE players SET last_drop_ts = $1 WHERE user_id = $2",
                datetime.now(timezone.utc), user_id
            )
            
            embed = discord.Embed(
                title="📦 Free Pack Claimed!",
                description=f"{ctx.author.mention} claimed **1 Normal Pack**!",
                color=discord.Color.green()
            )
            
            new_total = total_packs + 1
            embed.add_field(
                name="Pack Inventory",
                value=f"You now have **{new_total}/{MAX_TOTAL_PACKS}** packs",
                inline=False
            )
            
            embed.set_footer(text="Use !drop to open packs and get cards!")
            
            await ctx.send(embed=embed)
    
    @commands.command(name='mypacks')
    async def my_packs(self, ctx):
        """
        View your pack inventory.
        Usage: !mypacks
        """
        user_id = ctx.author.id
        
        async with self.db_pool.acquire() as conn:
            packs = await conn.fetch(
                "SELECT pack_type, quantity FROM user_packs WHERE user_id = $1 ORDER BY pack_type",
                user_id
            )
            
            total = await self.get_total_packs(conn, user_id)
            
            embed = discord.Embed(
                title=f"📦 {ctx.author.display_name}'s Pack Inventory",
                color=discord.Color.blue()
            )
            
            if not packs:
                embed.description = "You don't have any packs yet!\nUse `!claimfreepack` to get a free Normal Pack every 8 hours."
            else:
                pack_list = []
                for pack in packs:
                    pack_type = pack['pack_type']
                    qty = pack['quantity']
                    
                    # Add emoji based on pack type
                    if 'Normal' in pack_type:
                        emoji = "📦"
                    elif 'Booster Pack+' in pack_type:
                        emoji = "🎁"
                    elif 'Booster' in pack_type:
                        emoji = "🎁"
                    else:
                        emoji = "📦"
                    
                    pack_list.append(f"{emoji} **{pack_type}**: {qty}")
                
                embed.description = "\n".join(pack_list)
            
            embed.add_field(
                name="Total Packs",
                value=f"**{total}/{MAX_TOTAL_PACKS}**",
                inline=False
            )
            
            embed.set_footer(text="Use !drop [amount] [pack_type] to open packs")
            
            await ctx.send(embed=embed)
    
    @commands.command(name='offerpack')
    async def offer_pack_trade(self, ctx, target: discord.Member, pack_type: str, quantity: int = 1):
        """
        [PLACEHOLDER] Offer a pack trade to another user.
        Usage: !offerpack @user [pack_type] [quantity]
        Example: !offerpack @friend "Booster Pack" 2
        """
        await ctx.send(
            "🚧 **Pack Trading - Coming Soon!**\n"
            f"Pack trading functionality will be implemented in a future update.\n"
            f"You tried to offer **{quantity} {pack_type}** to {target.mention}"
        )
    
    @commands.command(name='acceptpacktrade')
    async def accept_pack_trade(self, ctx, trade_id: str):
        """
        [PLACEHOLDER] Accept a pending pack trade.
        Usage: !acceptpacktrade [trade_id]
        Example: !acceptpacktrade abc123
        """
        await ctx.send(
            "🚧 **Pack Trading - Coming Soon!**\n"
            f"Pack trading functionality will be implemented in a future update.\n"
            f"Trade ID: {trade_id}"
        )


async def setup(bot):
    await bot.add_cog(PackCommands(bot))
