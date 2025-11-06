"""
DeckForge Card Merge System Cog
Handles card merging with perk progression and diminishing returns
"""
import discord
from discord.ext import commands
from discord import app_commands
import asyncpg
import uuid
from typing import Optional, List

from utils.merge_helpers import (
    calculate_merge_cost,
    calculate_perk_boost,
    calculate_cumulative_perk_boost,
    get_merge_perks_for_deck,
    get_card_perk_history,
    validate_merge_eligibility,
    format_merge_level_display
)


class MergeCommands(commands.Cog):
    """Cog for card merging operations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_pool: asyncpg.Pool = bot.db_pool
    
    @commands.hybrid_command(name='merge')
    async def merge_cards(self, ctx, card_instance_1: str, card_instance_2: str, perk: Optional[str] = None):
        """
        Merge two cards of the same type and level to create a more powerful card
        
        Args:
            card_instance_1: First card instance ID (UUID)
            card_instance_2: Second card instance ID (UUID)
            perk: For first merge only - the perk to lock for future merges
        
        Usage:
            /merge <instance_id_1> <instance_id_2>
            /merge <instance_id_1> <instance_id_2> <perk_name>
        """
        # Defer for slash commands
        if ctx.interaction:
            await ctx.defer()
        
        user_id = ctx.author.id
        guild_id = ctx.guild.id if ctx.guild else None
        
        if not guild_id:
            await ctx.send("❌ This command can only be used in a server!")
            return
        
        # Check if server has an assigned deck
        deck = await self.bot.get_server_deck(guild_id)
        if not deck:
            await ctx.send(
                "❌ No deck assigned to this server!\n"
                "Ask a server manager to assign a deck via the web admin portal."
            )
            return
        
        deck_id = deck['deck_id']
        
        # Validate UUIDs
        try:
            instance_uuid_1 = uuid.UUID(card_instance_1)
            instance_uuid_2 = uuid.UUID(card_instance_2)
        except ValueError:
            await ctx.send("❌ Invalid card instance ID format! Use valid UUID.")
            return
        
        async with self.db_pool.acquire() as conn:
            # Validate merge eligibility
            is_valid, error_msg, card_data = await validate_merge_eligibility(
                conn, str(instance_uuid_1), str(instance_uuid_2), user_id
            )
            
            if not is_valid:
                await ctx.send(f"❌ {error_msg}")
                return
            
            current_level = card_data['merge_level']
            next_level = current_level + 1
            rarity = card_data['rarity']
            card_name = card_data['name']
            card_id = card_data['card_id']
            
            # Calculate merge cost
            merge_cost = calculate_merge_cost(rarity, current_level)
            
            # Check user balance
            player = await conn.fetchrow(
                "SELECT credits FROM players WHERE user_id = $1",
                user_id
            )
            
            if not player or player['credits'] < merge_cost:
                current_credits = player['credits'] if player else 0
                await ctx.send(
                    f"❌ Insufficient credits!\n"
                    f"Merge cost: **{merge_cost:,}** credits\n"
                    f"Your balance: **{current_credits:,}** credits\n"
                    f"Need: **{merge_cost - current_credits:,}** more credits"
                )
                return
            
            # For first merge (level 0 -> 1), require perk selection
            if current_level == 0:
                # Get available perks for this deck
                available_perks = await get_merge_perks_for_deck(conn, deck_id)
                
                if not available_perks:
                    await ctx.send(
                        f"❌ No merge perks configured for this deck!\n"
                        f"Contact a server admin to configure merge perks."
                    )
                    return
                
                if not perk:
                    # Show available perks
                    perk_list = "\n".join([f"• **{p['perk_name']}** (Base boost: +{p['base_boost']})" for p in available_perks])
                    await ctx.send(
                        f"🎯 **First Merge - Perk Selection Required**\n\n"
                        f"Choose a perk to lock for all future merges of this card:\n\n"
                        f"{perk_list}\n\n"
                        f"Usage: `/merge {card_instance_1} {card_instance_2} <perk_name>`"
                    )
                    return
                
                # Validate perk exists
                selected_perk = None
                for p in available_perks:
                    if p['perk_name'].lower() == perk.lower():
                        selected_perk = p
                        break
                
                if not selected_perk:
                    perk_names = ", ".join([f"**{p['perk_name']}**" for p in available_perks])
                    await ctx.send(
                        f"❌ Invalid perk name!\n"
                        f"Available perks: {perk_names}"
                    )
                    return
                
                locked_perk = selected_perk['perk_name']
                base_boost = selected_perk['base_boost']
                diminishing_factor = selected_perk['diminishing_factor']
            else:
                # Use locked perk from first card
                locked_perk = card_data['locked_perk']
                
                # Get perk configuration
                perk_config = await conn.fetchrow(
                    """SELECT base_boost, diminishing_factor
                       FROM deck_merge_perks
                       WHERE deck_id = $1 AND perk_name = $2""",
                    deck_id, locked_perk
                )
                
                if not perk_config:
                    await ctx.send(
                        f"❌ Perk configuration not found for **{locked_perk}**!\n"
                        f"Contact a server admin."
                    )
                    return
                
                base_boost = perk_config['base_boost']
                diminishing_factor = perk_config['diminishing_factor']
            
            # Calculate perk boost for new level
            perk_boost = calculate_perk_boost(base_boost, next_level, diminishing_factor)
            cumulative_boost = calculate_cumulative_perk_boost(base_boost, next_level, diminishing_factor)
            
            # Execute merge in transaction
            async with conn.transaction():
                # Deduct credits
                await conn.execute(
                    "UPDATE players SET credits = credits - $1 WHERE user_id = $2",
                    merge_cost, user_id
                )
                
                # Keep the first card, update it
                await conn.execute(
                    """UPDATE user_cards
                       SET merge_level = $1, locked_perk = $2
                       WHERE instance_id = $3""",
                    next_level, locked_perk, instance_uuid_1
                )
                
                # Recycle the second card (soft delete)
                await conn.execute(
                    """UPDATE user_cards
                       SET recycled_at = NOW()
                       WHERE instance_id = $1""",
                    instance_uuid_2
                )
                
                # Record perk application
                await conn.execute(
                    """INSERT INTO card_perks (instance_id, level_applied, characteristic_name, perk_value)
                       VALUES ($1, $2, $3, $4)""",
                    instance_uuid_1, next_level, locked_perk, perk_boost
                )
            
            # Create success embed
            embed = discord.Embed(
                title="✨ Merge Successful!",
                description=f"**{card_name}** {format_merge_level_display(current_level)} → {format_merge_level_display(next_level)}",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="New Merge Level",
                value=f"Level **{next_level}**",
                inline=True
            )
            
            embed.add_field(
                name="Credits Spent",
                value=f"{merge_cost:,}",
                inline=True
            )
            
            embed.add_field(
                name="Locked Perk",
                value=f"**{locked_perk}**",
                inline=True
            )
            
            embed.add_field(
                name="Perk Boost (This Level)",
                value=f"+{perk_boost}",
                inline=True
            )
            
            embed.add_field(
                name="Total Cumulative Boost",
                value=f"+{cumulative_boost}",
                inline=True
            )
            
            # Calculate next merge cost
            if next_level < card_data['max_merge_level']:
                next_merge_cost = calculate_merge_cost(rarity, next_level)
                embed.add_field(
                    name="Next Merge Cost",
                    value=f"{next_merge_cost:,} credits",
                    inline=True
                )
            else:
                embed.add_field(
                    name="Status",
                    value="🌟 MAX LEVEL REACHED!",
                    inline=False
                )
            
            embed.set_footer(text=f"Card Instance: {instance_uuid_1}")
            
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(MergeCommands(bot))
