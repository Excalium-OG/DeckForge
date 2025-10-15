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
    
    @commands.command(name='recycle')
    async def recycle_card(self, ctx, instance_id: str):
        """
        [PLACEHOLDER] Recycle a card for credits.
        Usage: !recycle [instance_id]
        """
        user_id = ctx.author.id
        
        try:
            # Validate UUID format
            import uuid
            card_uuid = uuid.UUID(instance_id)
        except ValueError:
            await ctx.send("❌ Invalid instance ID format!")
            return
        
        async with self.db_pool.acquire() as conn:
            # Check if card exists and belongs to user
            card = await conn.fetchrow(
                """SELECT uc.instance_id, uc.user_id, c.name, c.rarity
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
            
            # Delete the card (no credit reward yet)
            await conn.execute(
                "DELETE FROM user_cards WHERE instance_id = $1",
                card_uuid
            )
        
        await ctx.send(f"♻️ **{card['name']}** ({card['rarity']}) has been recycled! (Credit system coming in Phase 2)")
    
    @commands.command(name='buycredits')
    async def buy_credits(self, ctx, amount: int = 100):
        """
        [PLACEHOLDER] Simulate buying credits.
        Usage: !buycredits [amount]
        """
        user_id = ctx.author.id
        
        if amount <= 0 or amount > 10000:
            await ctx.send("❌ Amount must be between 1 and 10,000!")
            return
        
        async with self.db_pool.acquire() as conn:
            # Get or create player
            player = await conn.fetchrow(
                "SELECT user_id, credits FROM players WHERE user_id = $1",
                user_id
            )
            
            if not player:
                await conn.execute(
                    "INSERT INTO players (user_id, credits) VALUES ($1, $2)",
                    user_id, amount
                )
                new_balance = amount
            else:
                await conn.execute(
                    "UPDATE players SET credits = credits + $1 WHERE user_id = $2",
                    amount, user_id
                )
                new_balance = player['credits'] + amount
        
        embed = discord.Embed(
            title="💰 Credits Added (Simulation)",
            description=f"Added **{amount:,}** credits to your account!",
            color=discord.Color.gold()
        )
        embed.add_field(name="New Balance", value=f"{new_balance:,} credits", inline=False)
        embed.set_footer(text="Stripe integration coming in Phase 2")
        
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
    
    @commands.command(name='updateimage')
    async def update_image(self, ctx, card_id: int):
        """
        [ADMIN] Update a card's image.
        Usage: !updateimage [card_id]
        Requires: Image attachment
        """
        # Check admin permission
        if not self.is_admin(ctx.author.id):
            await ctx.send("❌ This command is admin-only!")
            return
        
        # Validate image attachment
        from utils.card_helpers import validate_image_attachment
        image_url = validate_image_attachment(ctx.message)
        
        if not image_url:
            await ctx.send("❌ You must attach an image!")
            return
        
        async with self.db_pool.acquire() as conn:
            # Check if card exists
            card = await conn.fetchrow(
                "SELECT card_id, name FROM cards WHERE card_id = $1",
                card_id
            )
            
            if not card:
                await ctx.send(f"❌ Card ID {card_id} not found!")
                return
            
            # Update image
            await conn.execute(
                "UPDATE cards SET image_url = $1 WHERE card_id = $2",
                image_url, card_id
            )
        
        embed = discord.Embed(
            title="🖼️ Image Updated!",
            description=f"**{card['name']}** now has a new image.",
            color=discord.Color.green()
        )
        embed.set_image(url=image_url)
        
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
