"""
DeckForge Slash Commands
Slash command implementations for Discord
"""
import discord
from discord import app_commands
from discord.ext import commands
import asyncpg
import uuid
from typing import Optional, List
from datetime import datetime, timezone

from utils.card_helpers import (
    validate_rarity,
    sort_cards_by_rarity,
    create_card_embed,
    RARITY_HIERARCHY
)
from utils.drop_helpers import get_default_drop_rates
from utils.pack_logic import validate_pack_type, format_pack_type


class SlashCommands(commands.Cog):
    """Cog for slash command implementations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_pool: asyncpg.Pool = bot.db_pool
        self.admin_ids = bot.admin_ids
    
    async def card_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for card names"""
        guild_id = interaction.guild_id
        if not guild_id:
            return []
        
        # Get server's assigned deck
        deck = await self.bot.get_server_deck(guild_id)
        if not deck:
            return []
        
        deck_id = deck['deck_id']
        
        # Search for cards matching the current input
        async with self.db_pool.acquire() as conn:
            cards = await conn.fetch(
                """SELECT card_id, name, rarity 
                   FROM cards 
                   WHERE deck_id = $1 AND LOWER(name) LIKE LOWER($2)
                   ORDER BY name
                   LIMIT 25""",
                deck_id,
                f"%{current}%"
            )
        
        return [
            app_commands.Choice(
                name=f"{card['name']} ({card['rarity']})",
                value=str(card['card_id'])
            )
            for card in cards
        ]
    
    @app_commands.command(name="cardinfo", description="View detailed information about a specific card")
    @app_commands.describe(
        card_name="The name of the card to look up",
        card_id="Or the card ID number to look up"
    )
    @app_commands.autocomplete(card_name=card_name_autocomplete)
    async def cardinfo(
        self,
        interaction: discord.Interaction,
        card_name: Optional[str] = None,
        card_id: Optional[int] = None
    ):
        """View detailed information about a specific card by name or ID"""
        guild_id = interaction.guild_id
        
        if not guild_id:
            await interaction.response.send_message("❌ This command can only be used in a server!", ephemeral=True)
            return
        
        # Check if server has an assigned deck
        deck = await self.bot.get_server_deck(guild_id)
        if not deck:
            await interaction.response.send_message(
                "❌ No deck assigned to this server!\n"
                "Ask a server manager to assign a deck via the web admin portal.",
                ephemeral=True
            )
            return
        
        deck_id = deck['deck_id']
        
        # Must provide either card_name or card_id
        if not card_name and not card_id:
            await interaction.response.send_message(
                "❌ Please provide either a card name or card ID!",
                ephemeral=True
            )
            return
        
        async with self.db_pool.acquire() as conn:
            if card_name:
                # If card_name is actually a card_id from autocomplete, try parsing it
                try:
                    parsed_id = int(card_name)
                    card = await conn.fetchrow(
                        """SELECT c.*, 
                           (SELECT COUNT(*) FROM user_cards uc 
                            WHERE uc.card_id = c.card_id AND uc.user_id = $2 AND uc.recycled_at IS NULL) as owned_count
                           FROM cards c
                           WHERE c.card_id = $1 AND c.deck_id = $3""",
                        parsed_id, interaction.user.id, deck_id
                    )
                except (ValueError, TypeError):
                    # Search by name
                    card = await conn.fetchrow(
                        """SELECT c.*, 
                           (SELECT COUNT(*) FROM user_cards uc 
                            WHERE uc.card_id = c.card_id AND uc.user_id = $2 AND uc.recycled_at IS NULL) as owned_count
                           FROM cards c
                           WHERE LOWER(c.name) = LOWER($1) AND c.deck_id = $3
                           LIMIT 1""",
                        card_name, interaction.user.id, deck_id
                    )
            else:
                # Search by card_id
                card = await conn.fetchrow(
                    """SELECT c.*, 
                       (SELECT COUNT(*) FROM user_cards uc 
                        WHERE uc.card_id = c.card_id AND uc.user_id = $2 AND uc.recycled_at IS NULL) as owned_count
                       FROM cards c
                       WHERE c.card_id = $1 AND c.deck_id = $3""",
                    card_id, interaction.user.id, deck_id
                )
            
            if not card:
                await interaction.response.send_message(
                    "❌ Card not found in this deck!",
                    ephemeral=True
                )
                return
            
            # Get custom template fields for this card
            template_fields = await conn.fetch(
                """SELECT ctf.field_value, ct.field_name, ct.field_type
                   FROM card_template_fields ctf
                   JOIN card_templates ct ON ctf.template_id = ct.template_id
                   WHERE ctf.card_id = $1
                   ORDER BY ct.display_order""",
                card['card_id']
            )
        
        # Create embed
        embed = create_card_embed(card)
        
        # Add custom template fields
        if template_fields:
            for field in template_fields:
                embed.add_field(
                    name=field['field_name'],
                    value=field['field_value'] or 'N/A',
                    inline=True
                )
        
        # Add ownership info
        embed.add_field(
            name="You Own",
            value=f"{card['owned_count']} copies",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="balance", description="Check your credit balance")
    async def balance(self, interaction: discord.Interaction):
        """Check your credit balance"""
        user_id = interaction.user.id
        
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
        embed.add_field(
            name="💡 How to Earn Credits",
            value="• Recycle duplicate cards with `/recycle`\n• Microtransactions coming soon!",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="help", description="Get help with DeckForge commands")
    async def help_command(self, interaction: discord.Interaction):
        """Display help information about available commands"""
        embed = discord.Embed(
            title="🚀 DeckForge Help",
            description="Collect rocket-themed trading cards and build your collection!",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📦 Pack Commands",
            value=(
                "`/drop [amount] [pack_type]` - Open packs to get cards\n"
                "`/claimfreepack` - Claim a free Normal Pack (cooldown based on deck)\n"
                "`/buypack [pack_type] [amount]` - Purchase packs with credits"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🎴 Collection Commands",
            value=(
                "`/mycards [page]` - View your card collection\n"
                "`/cardinfo` - View detailed info about a card (with autocomplete)\n"
                "`/recycle` - Convert duplicate cards into credits"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💰 Economy Commands",
            value=(
                "`/balance` - Check your credit balance\n"
                "`/buycredits` - Info about purchasing credits"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🔄 Trading Commands",
            value=(
                "`/requesttrade @user` - Start a trade with another player\n"
                "`/tradeadd [instance_id]` - Add a card to active trade\n"
                "`/traderemove [instance_id]` - Remove a card from trade\n"
                "`/accepttrade` - Accept the current trade offer\n"
                "`/finalize` - Complete and finalize the trade"
            ),
            inline=False
        )
        
        embed.set_footer(text="Use autocomplete to easily find cards by name!")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="drop", description="Open packs to get cards")
    @app_commands.describe(
        amount="Number of packs to open (default: 1)",
        pack_type="Type of pack: Normal, Booster, or Booster+"
    )
    @app_commands.choices(pack_type=[
        app_commands.Choice(name="Normal Pack", value="Normal Pack"),
        app_commands.Choice(name="Booster Pack", value="Booster Pack"),
        app_commands.Choice(name="Booster+ Pack", value="Booster+ Pack")
    ])
    async def drop(
        self,
        interaction: discord.Interaction,
        amount: int = 1,
        pack_type: str = "Normal Pack"
    ):
        """Open packs to get cards"""
        # Defer response since this might take a moment
        await interaction.response.defer()
        
        # Get the CardCommands cog
        cards_cog = self.bot.get_cog('CardCommands')
        if not cards_cog:
            await interaction.followup.send("❌ Command temporarily unavailable!")
            return
        
        # Create a fake context object for the prefix command
        # We'll create a minimal context that the command can use
        class FakeMessage:
            def __init__(self, author, guild, channel):
                self.author = author
                self.guild = guild
                self.channel = channel
        
        fake_msg = FakeMessage(interaction.user, interaction.guild, interaction.channel)
        ctx = await self.bot.get_context(fake_msg)
        ctx.send = interaction.followup.send  # Override send to use followup
        
        # Call the drop command
        try:
            await cards_cog.drop_cards(ctx, amount, pack_type)
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: {str(e)}")
    
    @app_commands.command(name="mycards", description="View your card collection")
    @app_commands.describe(page="Page number to view (default: 1)")
    async def mycards(
        self,
        interaction: discord.Interaction,
        page: int = 1
    ):
        """View your card collection"""
        await interaction.response.defer()
        
        cards_cog = self.bot.get_cog('CardCommands')
        if not cards_cog:
            await interaction.followup.send("❌ Command temporarily unavailable!")
            return
        
        class FakeMessage:
            def __init__(self, author, guild, channel):
                self.author = author
                self.guild = guild
                self.channel = channel
        
        fake_msg = FakeMessage(interaction.user, interaction.guild, interaction.channel)
        ctx = await self.bot.get_context(fake_msg)
        ctx.send = interaction.followup.send
        
        try:
            await cards_cog.my_cards(ctx)
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: {str(e)}")
    
    @app_commands.command(name="recycle", description="Convert duplicate cards into credits")
    async def recycle_slash(self, interaction: discord.Interaction):
        """Recycle duplicate cards for credits"""
        await interaction.response.defer()
        
        cards_cog = self.bot.get_cog('CardCommands')
        if not cards_cog:
            await interaction.followup.send("❌ Command temporarily unavailable!")
            return
        
        class FakeMessage:
            def __init__(self, author, guild, channel):
                self.author = author
                self.guild = guild
                self.channel = channel
        
        fake_msg = FakeMessage(interaction.user, interaction.guild, interaction.channel)
        ctx = await self.bot.get_context(fake_msg)
        ctx.send = interaction.followup.send
        
        try:
            await cards_cog.recycle_cards(ctx)
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: {str(e)}")
    
    @app_commands.command(name="claimfreepack", description="Claim your free pack (cooldown based on deck)")
    async def claimfreepack(self, interaction: discord.Interaction):
        """Claim a free pack"""
        await interaction.response.defer()
        
        packs_cog = self.bot.get_cog('PackCommands')
        if not packs_cog:
            await interaction.followup.send("❌ Command temporarily unavailable!")
            return
        
        class FakeMessage:
            def __init__(self, author, guild, channel):
                self.author = author
                self.guild = guild
                self.channel = channel
        
        fake_msg = FakeMessage(interaction.user, interaction.guild, interaction.channel)
        ctx = await self.bot.get_context(fake_msg)
        ctx.send = interaction.followup.send
        
        try:
            await packs_cog.claim_free_pack(ctx)
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: {str(e)}")
    
    @app_commands.command(name="buypack", description="Purchase packs with credits")
    @app_commands.describe(
        pack_type="Type of pack to purchase",
        amount="Number of packs to buy (default: 1)"
    )
    @app_commands.choices(pack_type=[
        app_commands.Choice(name="Normal Pack", value="Normal Pack"),
        app_commands.Choice(name="Booster Pack", value="Booster Pack"),
        app_commands.Choice(name="Booster+ Pack", value="Booster+ Pack")
    ])
    async def buypack(
        self,
        interaction: discord.Interaction,
        pack_type: str,
        amount: int = 1
    ):
        """Purchase packs with credits"""
        await interaction.response.defer()
        
        packs_cog = self.bot.get_cog('PackCommands')
        if not packs_cog:
            await interaction.followup.send("❌ Command temporarily unavailable!")
            return
        
        class FakeMessage:
            def __init__(self, author, guild, channel):
                self.author = author
                self.guild = guild
                self.channel = channel
        
        fake_msg = FakeMessage(interaction.user, interaction.guild, interaction.channel)
        ctx = await self.bot.get_context(fake_msg)
        ctx.send = interaction.followup.send
        
        try:
            await packs_cog.buy_pack(ctx, pack_type, amount)
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: {str(e)}")
    
    @app_commands.command(name="buycredits", description="Information about purchasing credits")
    async def buycredits(self, interaction: discord.Interaction):
        """Get information about buying credits"""
        embed = discord.Embed(
            title="💳 Purchase Credits",
            description="Credit purchases are not yet available!\n\n"
                       "**How to earn credits:**\n"
                       "• Recycle duplicate cards using `/recycle`\n"
                       "• Microtransactions coming soon via Stripe integration",
            color=discord.Color.gold()
        )
        embed.set_footer(text="Credits can only be earned by recycling cards for now")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(SlashCommands(bot))
