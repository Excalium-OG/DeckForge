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
from utils.drop_helpers import (
    get_default_drop_rates,
    validate_drop_rates,
    select_rarity_by_weight,
    format_drop_rates_table
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
    
    async def get_guild_drop_rates(self, conn, guild_id: Optional[int]) -> dict:
        """Get drop rates for a guild, or defaults if not configured"""
        if not guild_id:
            return get_default_drop_rates()
        
        # Fetch guild-specific rates
        rates_rows = await conn.fetch(
            "SELECT rarity, percentage FROM drop_rates WHERE guild_id = $1",
            guild_id
        )
        
        if not rates_rows:
            return get_default_drop_rates()
        
        rates = {row['rarity']: row['percentage'] for row in rates_rows}
        
        # Ensure all rarities are present
        for rarity in RARITY_HIERARCHY:
            if rarity not in rates:
                return get_default_drop_rates()
        
        return rates
    
    @commands.command(name='drop')
    async def drop_cards(self, ctx):
        """
        Claim 2 randomized cards every 8 hours.
        Usage: !drop
        """
        user_id = ctx.author.id
        guild_id = ctx.guild.id if ctx.guild else None
        
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
            
            # Get all available cards grouped by rarity
            all_cards = await conn.fetch("SELECT card_id, name, rarity FROM cards")
            
            if len(all_cards) == 0:
                await ctx.send("❌ No cards in the database! Admin needs to add cards using `!addcard`.")
                return
            
            # Group cards by rarity
            cards_by_rarity = {}
            for card in all_cards:
                rarity = card['rarity']
                if rarity not in cards_by_rarity:
                    cards_by_rarity[rarity] = []
                cards_by_rarity[rarity].append(card)
            
            # Get drop rates for this guild
            drop_rates = await self.get_guild_drop_rates(conn, guild_id)
            
            # Select 2 cards using weighted rarity selection
            dropped_cards = []
            for _ in range(2):
                # Select rarity based on weights
                selected_rarity = select_rarity_by_weight(drop_rates)
                
                # Get cards of this rarity
                available_cards = cards_by_rarity.get(selected_rarity, [])
                
                # If no cards of this rarity exist, try again with any available rarity
                if not available_cards:
                    available_rarities = list(cards_by_rarity.keys())
                    if not available_rarities:
                        continue
                    selected_rarity = random.choice(available_rarities)
                    available_cards = cards_by_rarity[selected_rarity]
                
                # Select random card from this rarity
                selected_card = random.choice(available_cards)
                dropped_cards.append(selected_card)
            
            if not dropped_cards:
                await ctx.send("❌ Unable to drop cards. Please contact an admin.")
                return
            
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
    
    @commands.command(name='viewdroprates')
    async def view_drop_rates(self, ctx):
        """
        View current drop rates for this server.
        Usage: !viewdroprates
        """
        guild_id = ctx.guild.id if ctx.guild else None
        
        if not guild_id:
            await ctx.send("❌ This command can only be used in a server!")
            return
        
        async with self.db_pool.acquire() as conn:
            drop_rates = await self.get_guild_drop_rates(conn, guild_id)
        
        # Check if using defaults
        rates_rows = await self.db_pool.fetchrow(
            "SELECT COUNT(*) as count FROM drop_rates WHERE guild_id = $1",
            guild_id
        )
        using_defaults = rates_rows['count'] == 0 if rates_rows else True
        
        embed = discord.Embed(
            title="🎲 Drop Rates Configuration",
            description="Current card drop rates for this server:",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Drop Rates",
            value=format_drop_rates_table(drop_rates),
            inline=False
        )
        
        if using_defaults:
            embed.set_footer(text="Using default rates. Admins can customize with !setdroprate")
        else:
            embed.set_footer(text="Custom rates configured for this server")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='setdroprate')
    async def set_drop_rate(self, ctx, rarity: str, percentage: float):
        """
        [ADMIN] Set the drop rate for a specific rarity.
        Usage: !setdroprate [rarity] [percentage]
        Example: !setdroprate Legendary 5
        """
        # Check admin permission
        if not self.is_admin(ctx.author.id):
            await ctx.send("❌ This command is admin-only!")
            return
        
        guild_id = ctx.guild.id if ctx.guild else None
        if not guild_id:
            await ctx.send("❌ This command can only be used in a server!")
            return
        
        # Validate rarity
        rarity = rarity.capitalize()
        if not validate_rarity(rarity):
            await ctx.send(
                f"❌ Invalid rarity! Must be one of: {', '.join(RARITY_HIERARCHY)}"
            )
            return
        
        # Validate percentage
        if percentage < 0 or percentage > 100:
            await ctx.send("❌ Percentage must be between 0 and 100!")
            return
        
        async with self.db_pool.acquire() as conn:
            # Get current rates for this guild
            current_rates = await self.get_guild_drop_rates(conn, guild_id)
            
            # Update the specified rarity
            current_rates[rarity] = percentage
            
            # Validate total sum
            is_valid, error_msg = validate_drop_rates(current_rates)
            if not is_valid:
                await ctx.send(f"❌ {error_msg}")
                return
            
            # Update database - store ALL rarities for this guild to ensure consistency
            async with conn.transaction():
                # Delete existing rates for this guild
                await conn.execute(
                    "DELETE FROM drop_rates WHERE guild_id = $1",
                    guild_id
                )
                
                # Insert all rarities with updated values
                for r in RARITY_HIERARCHY:
                    await conn.execute(
                        """INSERT INTO drop_rates (guild_id, rarity, percentage)
                           VALUES ($1, $2, $3)""",
                        guild_id, r, current_rates[r]
                    )
        
        # Show updated rates
        embed = discord.Embed(
            title="✅ Drop Rate Updated!",
            description=f"**{rarity}** drop rate set to **{percentage}%**",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Updated Rates",
            value=format_drop_rates_table(current_rates),
            inline=False
        )
        
        total = sum(current_rates.values())
        if abs(total - 100.0) < 0.01:
            embed.set_footer(text="✅ All rates configured correctly (total = 100%)")
        else:
            embed.set_footer(text=f"⚠️ Total is {total}% - adjust other rarities to reach 100%")
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(CardCommands(bot))
