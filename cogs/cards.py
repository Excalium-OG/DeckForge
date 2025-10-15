"""
DeckForge Card Commands Cog
Handles all card-related commands for the trading card bot
"""
import discord
from discord.ext import commands
import asyncpg
import uuid
import random
from datetime import datetime, timezone
from typing import Optional

from utils.card_helpers import (
    validate_rarity,
    sort_cards_by_rarity,
    check_drop_cooldown,
    format_cooldown_time,
    validate_image_attachment,
    create_card_embed,
    RARITY_HIERARCHY
)


class CardCommands(commands.Cog):
    """Cog for card collection and management commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_pool: asyncpg.Pool = bot.db_pool
        self.admin_ids = bot.admin_ids
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        return user_id in self.admin_ids or user_id == self.bot.owner_id
    
    @commands.command(name='drop')
    async def drop_cards(self, ctx):
        """
        Claim 2 randomized cards every 8 hours.
        Usage: !drop
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
            
            # Check cooldown
            can_drop, time_remaining = check_drop_cooldown(last_drop_ts)
            
            if not can_drop and time_remaining:
                cooldown_str = format_cooldown_time(time_remaining)
                await ctx.send(f"⏰ You can drop cards again in **{cooldown_str}**!")
                return
            
            # Get all available cards
            all_cards = await conn.fetch("SELECT card_id, name, rarity FROM cards")
            
            if len(all_cards) < 2:
                await ctx.send("❌ Not enough cards in the database! Admin needs to add more cards using `!addcard`.")
                return
            
            # Randomly select 2 cards
            dropped_cards = random.sample(list(all_cards), min(2, len(all_cards)))
            
            # Insert card instances
            instances = []
            for card in dropped_cards:
                instance_id = uuid.uuid4()
                await conn.execute(
                    """INSERT INTO user_cards (instance_id, user_id, card_id, acquired_at, source)
                       VALUES ($1, $2, $3, $4, $5)""",
                    instance_id, user_id, card['card_id'], datetime.now(timezone.utc), 'drop'
                )
                instances.append({
                    'instance_id': str(instance_id),
                    'name': card['name'],
                    'rarity': card['rarity']
                })
            
            # Update last drop timestamp
            await conn.execute(
                "UPDATE players SET last_drop_ts = $1 WHERE user_id = $2",
                datetime.now(timezone.utc), user_id
            )
        
        # Send response
        embed = discord.Embed(
            title="🚀 Card Drop!",
            description=f"{ctx.author.mention} received:",
            color=discord.Color.blue()
        )
        
        for inst in instances:
            embed.add_field(
                name=f"{inst['name']} ({inst['rarity']})",
                value=f"Instance: `{inst['instance_id']}`",
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='mycards')
    async def my_cards(self, ctx):
        """
        List all owned cards, sorted by rarity then alphabetically.
        Usage: !mycards
        """
        user_id = ctx.author.id
        
        async with self.db_pool.acquire() as conn:
            cards = await conn.fetch(
                """SELECT uc.instance_id, c.card_id, c.name, c.rarity, c.image_url
                   FROM user_cards uc
                   JOIN cards c ON uc.card_id = c.card_id
                   WHERE uc.user_id = $1
                   ORDER BY uc.acquired_at DESC""",
                user_id
            )
        
        if not cards:
            await ctx.send("📦 You don't have any cards yet! Use `!drop` to get your first cards.")
            return
        
        # Convert to list of dicts and sort
        cards_list = [dict(card) for card in cards]
        sorted_cards = sort_cards_by_rarity(cards_list)
        
        # Create embed
        embed = discord.Embed(
            title=f"🎴 {ctx.author.name}'s Card Collection",
            description=f"Total cards: {len(sorted_cards)}",
            color=discord.Color.green()
        )
        
        # Group by rarity for better display
        current_rarity = None
        rarity_cards = []
        
        for card in sorted_cards:
            if card['rarity'] != current_rarity:
                if rarity_cards:
                    embed.add_field(
                        name=f"⭐ {current_rarity}",
                        value="\n".join(rarity_cards),
                        inline=False
                    )
                current_rarity = card['rarity']
                rarity_cards = []
            
            rarity_cards.append(f"• **{card['name']}** (ID: {card['card_id']})")
        
        # Add last group
        if rarity_cards:
            embed.add_field(
                name=f"⭐ {current_rarity}",
                value="\n".join(rarity_cards),
                inline=False
            )
        
        # Set thumbnail if user has cards with images
        for card in sorted_cards:
            if card.get('image_url'):
                embed.set_thumbnail(url=card['image_url'])
                break
        
        await ctx.send(embed=embed)
    
    @commands.command(name='cardinfo')
    async def card_info(self, ctx, *, search_term: str):
        """
        Show detailed information about a card.
        Usage: !cardinfo [name or ID]
        """
        async with self.db_pool.acquire() as conn:
            # Try to parse as card_id first
            try:
                card_id = int(search_term)
                card = await conn.fetchrow(
                    "SELECT * FROM cards WHERE card_id = $1",
                    card_id
                )
            except ValueError:
                # Search by name (case-insensitive)
                card = await conn.fetchrow(
                    "SELECT * FROM cards WHERE LOWER(name) = LOWER($1)",
                    search_term
                )
        
        if not card:
            await ctx.send(f"❌ No card found with name or ID: `{search_term}`")
            return
        
        # Create embed
        card_dict = dict(card)
        embed = create_card_embed(card_dict)
        
        # Add creation info
        if card_dict.get('created_by'):
            try:
                creator = await self.bot.fetch_user(card_dict['created_by'])
                embed.set_footer(text=f"Created by {creator.name}")
            except:
                pass
        
        await ctx.send(embed=embed)
    
    @commands.command(name='addcard')
    async def add_card(self, ctx, rarity: str, name: str, *, description: str = ""):
        """
        [ADMIN] Add a new card to the database with image.
        Usage: !addcard [rarity] [name_with_underscores] [description_with_underscores]
        Requires: Image attachment
        """
        # Check admin permission
        if not self.is_admin(ctx.author.id):
            await ctx.send("❌ This command is admin-only!")
            return
        
        # Validate rarity
        rarity = rarity.capitalize()
        if not validate_rarity(rarity):
            await ctx.send(
                f"❌ Invalid rarity! Must be one of: {', '.join(RARITY_HIERARCHY)}"
            )
            return
        
        # Validate image attachment
        image_url = validate_image_attachment(ctx.message)
        if not image_url:
            await ctx.send("❌ You must attach an image when creating a card!")
            return
        
        # Replace underscores with spaces in name and description
        name = name.replace('_', ' ')
        description = description.replace('_', '\n')
        
        async with self.db_pool.acquire() as conn:
            # Insert card
            card_id = await conn.fetchval(
                """INSERT INTO cards (name, rarity, description, image_url, created_by)
                   VALUES ($1, $2, $3, $4, $5)
                   RETURNING card_id""",
                name, rarity, description, image_url, ctx.author.id
            )
        
        # Confirmation embed
        embed = discord.Embed(
            title="✅ Card Created!",
            description=f"**{name}** has been added to the collection.",
            color=discord.Color.green()
        )
        embed.add_field(name="Card ID", value=str(card_id), inline=True)
        embed.add_field(name="Rarity", value=rarity, inline=True)
        embed.add_field(name="Description", value=description or "None", inline=False)
        embed.set_image(url=image_url)
        
        await ctx.send(embed=embed)
    


async def setup(bot):
    await bot.add_cog(CardCommands(bot))
