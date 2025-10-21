"""
DeckForge Future Features Cog
Placeholder commands for Phase 2+ features
"""
import discord
from discord.ext import commands
import asyncpg
from typing import Optional


class FutureCommands(commands.Cog):
    """Cog for placeholder/future feature commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_pool: asyncpg.Pool = bot.db_pool
        self.admin_ids = bot.admin_ids
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        return user_id in self.admin_ids or user_id == self.bot.owner_id
    
    @commands.command(name='buycredits')
    async def buy_credits(self, ctx):
        """
        Purchase credits with real money (microtransactions).
        Usage: !buycredits
        """
        embed = discord.Embed(
            title="💳 Purchase Credits",
            description="Credit purchases are not yet available!\n\n"
                       "**How to earn credits:**\n"
                       "• Recycle duplicate cards using `!recycle`\n"
                       "• Microtransactions coming soon via Stripe integration",
            color=discord.Color.gold()
        )
        embed.set_footer(text="Credits can only be earned by recycling cards for now")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='launch')
    async def launch_card(self, ctx, instance_id: str):
        """
        [PLACEHOLDER] Launch a rocket card.
        Usage: !launch [instance_id]
        """
        user_id = ctx.author.id
        
        try:
            import uuid
            card_uuid = uuid.UUID(instance_id)
        except ValueError:
            await ctx.send("❌ Invalid instance ID format!")
            return
        
        async with self.db_pool.acquire() as conn:
            # Verify ownership
            card = await conn.fetchrow(
                """SELECT uc.instance_id, uc.user_id, c.name, c.rarity, c.stats
                   FROM user_cards uc
                   JOIN cards c ON uc.card_id = c.card_id
                   WHERE uc.instance_id = $1""",
                card_uuid
            )
            
            if not card:
                await ctx.send("❌ Card not found!")
                return
            
            if card['user_id'] != user_id:
                await ctx.send("❌ You don't own this card!")
                return
        
        embed = discord.Embed(
            title="🚀 Launch Sequence Initiated!",
            description=f"**{card['name']}** ({card['rarity']}) is preparing for launch...",
            color=discord.Color.blue()
        )
        embed.add_field(name="Status", value="Gameplay mechanics coming in Phase 2!", inline=False)
        embed.set_footer(text="Instance: " + instance_id)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='balance')
    async def check_balance(self, ctx):
        """
        Check your credit balance.
        Usage: !balance
        """
        user_id = ctx.author.id
        
        async with self.db_pool.acquire() as conn:
            player = await conn.fetchrow(
                "SELECT credits FROM players WHERE user_id = $1",
                user_id
            )
        
        if not player:
            credits = 0
        else:
            credits = player['credits']
        
        embed = discord.Embed(
            title="💰 Credit Balance",
            description=f"You have **{credits:,}** credits",
            color=discord.Color.gold()
        )
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(FutureCommands(bot))
