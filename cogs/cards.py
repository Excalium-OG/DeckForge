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
from utils.pack_logic import (
    validate_pack_type,
    format_pack_type,
    apply_pack_modifier
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
    async def drop_cards(self, ctx, amount: int = 1, pack_type: str = "Normal Pack"):
        """
        Open packs to get cards. Each pack gives 2 cards.
        Usage: !drop [amount] [pack_type]
        Examples: !drop, !drop 2, !drop 1 "Booster Pack"
        """
        user_id = ctx.author.id
        guild_id = ctx.guild.id if ctx.guild else None
        
        # Validate amount
        if amount < 1 or amount > 10:
            await ctx.send("❌ You can open 1-10 packs at a time!")
            return
        
        # Format and validate pack type
        pack_type = format_pack_type(pack_type)
        if not validate_pack_type(pack_type):
            await ctx.send(
                f"❌ Invalid pack type! Must be one of: Normal Pack, Booster Pack, Booster Pack+"
            )
            return
        
        async with self.db_pool.acquire() as conn:
            # Check if user has enough packs
            current_qty = await conn.fetchval(
                "SELECT quantity FROM user_packs WHERE user_id = $1 AND pack_type = $2",
                user_id, pack_type
            )
            
            if not current_qty or current_qty < amount:
                await ctx.send(
                    f"❌ You don't have enough **{pack_type}**s!\n"
                    f"You have: **{current_qty or 0}**, need: **{amount}**\n"
                    f"Use `!mypacks` to see your inventory or `!claimfreepack` for a free pack."
                )
                return
            
            # Remove packs from inventory
            new_qty = current_qty - amount
            if new_qty == 0:
                await conn.execute(
                    "DELETE FROM user_packs WHERE user_id = $1 AND pack_type = $2",
                    user_id, pack_type
                )
            else:
                await conn.execute(
                    "UPDATE user_packs SET quantity = $3 WHERE user_id = $1 AND pack_type = $2",
                    user_id, pack_type, new_qty
                )
            
            # Get all available cards grouped by rarity
            all_cards = await conn.fetch("SELECT card_id, name, rarity FROM cards")
            
            if len(all_cards) == 0:
                # Refund packs
                await conn.execute(
                    """INSERT INTO user_packs (user_id, pack_type, quantity)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (user_id, pack_type)
                       DO UPDATE SET quantity = user_packs.quantity + $3""",
                    user_id, pack_type, amount
                )
                await ctx.send("❌ No cards in the database! Admin needs to add cards using `!addcard`.")
                return
            
            # Group cards by rarity
            cards_by_rarity = {}
            for card in all_cards:
                rarity = card['rarity']
                if rarity not in cards_by_rarity:
                    cards_by_rarity[rarity] = []
                cards_by_rarity[rarity].append(card)
            
            # Get base drop rates for this guild
            base_rates = await self.get_guild_drop_rates(conn, guild_id)
            
            # Apply pack modifier to get modified drop rates
            drop_rates = apply_pack_modifier(base_rates, pack_type)
            
            # Open packs (2 cards per pack)
            dropped_cards = []
            for _ in range(amount * 2):
                # Select rarity based on modified weights
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
                    instance_id, user_id, card['card_id'], datetime.now(timezone.utc), 'pack'
                )
                instances.append({
                    'instance_id': str(instance_id),
                    'name': card['name'],
                    'rarity': card['rarity']
                })
        
        # Send response
        pack_emoji = "📦" if pack_type == "Normal Pack" else "🎁"
        embed = discord.Embed(
            title=f"{pack_emoji} Opened {amount} {pack_type}{'s' if amount > 1 else ''}!",
            description=f"{ctx.author.mention} received {len(instances)} cards:",
            color=discord.Color.purple()
        )
        
        # Group cards by rarity for display
        rarity_groups = {}
        for inst in instances:
            rarity = inst['rarity']
            if rarity not in rarity_groups:
                rarity_groups[rarity] = []
            rarity_groups[rarity].append(inst['name'])
        
        # Display by rarity
        for rarity in RARITY_HIERARCHY:
            if rarity in rarity_groups:
                cards = rarity_groups[rarity]
                embed.add_field(
                    name=f"{rarity} ({len(cards)})",
                    value=", ".join(cards),
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
            await ctx.send("📦 You don't have any cards yet! Use `!claimfreepack` to get a pack, then `!drop` to open it.")
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
