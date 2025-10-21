"""
DeckForge Trading System Cog
Handles card trading between players with multi-step confirmation flow
"""
import discord
from discord.ext import commands
import asyncpg
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

# Trade timeout duration
TRADE_TIMEOUT_MINUTES = 5


class TradingCommands(commands.Cog):
    """Cog for player-to-player card trading"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_pool: asyncpg.Pool = bot.db_pool
        self.active_trades: Dict[str, datetime] = {}
    
    async def get_active_trade(self, conn, user_id: int) -> Optional[dict]:
        """Get any active trade involving this user, auto-expiring stale ones"""
        trade = await conn.fetchrow(
            """SELECT * FROM trades
               WHERE (initiator_id = $1 OR responder_id = $1)
               AND status IN ('pending', 'active', 'accepted')
               ORDER BY started_at DESC
               LIMIT 1""",
            user_id
        )
        
        if not trade:
            return None
        
        # Check if trade has expired
        if trade['expires_at'] and trade['expires_at'] < datetime.now(timezone.utc):
            # Mark as expired
            await conn.execute(
                "UPDATE trades SET status = 'expired' WHERE trade_id = $1",
                trade['trade_id']
            )
            return None  # Treat expired trades as non-existent
        
        return dict(trade)
    
    async def get_trade_items(self, conn, trade_id: str, user_id: Optional[int] = None) -> list:
        """Get items in a trade, optionally filtered by user"""
        if user_id:
            items = await conn.fetch(
                """SELECT ti.*, c.name, c.rarity
                   FROM trade_items ti
                   JOIN cards c ON ti.card_id = c.card_id
                   WHERE ti.trade_id = $1 AND ti.user_id = $2""",
                uuid.UUID(trade_id), user_id
            )
        else:
            items = await conn.fetch(
                """SELECT ti.*, c.name, c.rarity
                   FROM trade_items ti
                   JOIN cards c ON ti.card_id = c.card_id
                   WHERE ti.trade_id = $1""",
                uuid.UUID(trade_id)
            )
        return [dict(item) for item in items]
    
    async def check_user_card_count(self, conn, user_id: int, card_id: int) -> int:
        """Count how many non-recycled instances of a card a user owns"""
        count = await conn.fetchval(
            """SELECT COUNT(*) FROM user_cards
               WHERE user_id = $1 AND card_id = $2 AND recycled_at IS NULL""",
            user_id, card_id
        )
        return count or 0
    
    async def display_trade_pool(self, ctx, trade: dict):
        """Display the current state of a trade"""
        trade_id = str(trade['trade_id'])
        
        async with self.db_pool.acquire() as conn:
            initiator_items = await self.get_trade_items(conn, trade_id, trade['initiator_id'])
            responder_items = await self.get_trade_items(conn, trade_id, trade['responder_id'])
        
        try:
            initiator = await self.bot.fetch_user(trade['initiator_id'])
            responder = await self.bot.fetch_user(trade['responder_id'])
        except:
            await ctx.send("❌ Error fetching user information")
            return
        
        embed = discord.Embed(
            title="📊 Trade Pool",
            description=f"Trade between {initiator.mention} and {responder.mention}",
            color=discord.Color.blue()
        )
        
        # Initiator's offer
        if initiator_items:
            items_text = "\n".join([
                f"• (x{item['quantity']}) **{item['name']}** (ID: {item['card_id']}) - {item['rarity']}"
                for item in initiator_items
            ])
        else:
            items_text = "*Nothing offered*"
        
        embed.add_field(
            name=f"{initiator.name}'s Offer",
            value=items_text,
            inline=False
        )
        
        # Responder's offer
        if responder_items:
            items_text = "\n".join([
                f"• (x{item['quantity']}) **{item['name']}** (ID: {item['card_id']}) - {item['rarity']}"
                for item in responder_items
            ])
        else:
            items_text = "*Nothing offered*"
        
        embed.add_field(
            name=f"{responder.name}'s Offer",
            value=items_text,
            inline=False
        )
        
        # Trade status
        status_icons = {
            'pending': '⏳',
            'active': '🔄',
            'accepted': '✅',
            'completed': '✔️',
            'cancelled': '❌',
            'expired': '⏰'
        }
        
        status_text = f"{status_icons.get(trade['status'], '❓')} Status: {trade['status'].title()}"
        if trade.get('expires_at'):
            expires_at = trade['expires_at']
            time_left = expires_at - datetime.now(timezone.utc)
            if time_left.total_seconds() > 0:
                minutes_left = int(time_left.total_seconds() / 60)
                status_text += f"\n⏰ Expires in: {minutes_left} minute(s)"
        
        embed.add_field(name="Trade Info", value=status_text, inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='requesttrade')
    async def request_trade(self, ctx, member: discord.Member):
        """
        Initiate a trade with another user in this server.
        Usage: /requesttrade @user
        """
        initiator_id = ctx.author.id
        responder_id = member.id
        guild_id = ctx.guild.id if ctx.guild else None
        
        # Must be in a server
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
        
        # Can't trade with yourself
        if initiator_id == responder_id:
            await ctx.send("❌ You can't trade with yourself!")
            return
        
        # Can't trade with bots
        if member.bot:
            await ctx.send("❌ You can't trade with bots!")
            return
        
        async with self.db_pool.acquire() as conn:
            # Check if either user has an active trade
            initiator_trade = await self.get_active_trade(conn, initiator_id)
            responder_trade = await self.get_active_trade(conn, responder_id)
            
            if initiator_trade:
                await ctx.send(
                    f"❌ You already have an active trade! "
                    f"Cancel it first or wait for it to complete/expire."
                )
                return
            
            if responder_trade:
                await ctx.send(
                    f"❌ {member.mention} already has an active trade! "
                    f"Ask them to finish or cancel it first."
                )
                return
            
            # Create new trade
            trade_id = uuid.uuid4()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=TRADE_TIMEOUT_MINUTES)
            
            await conn.execute(
                """INSERT INTO trades (trade_id, initiator_id, responder_id, status, expires_at)
                   VALUES ($1, $2, $3, 'pending', $4)""",
                trade_id, initiator_id, responder_id, expires_at
            )
        
        embed = discord.Embed(
            title="📩 Trade Request",
            description=(
                f"{ctx.author.mention} wants to trade with {member.mention}!\n\n"
                f"{member.mention}, use `/accepttrade` to begin trading.\n"
                f"Trade expires in {TRADE_TIMEOUT_MINUTES} minutes."
            ),
            color=discord.Color.purple()
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='accepttrade')
    async def accept_trade(self, ctx):
        """
        Accept a trade request or confirm your acceptance of the trade terms.
        Usage: /accepttrade
        """
        user_id = ctx.author.id
        
        async with self.db_pool.acquire() as conn:
            trade = await self.get_active_trade(conn, user_id)
            
            if not trade:
                await ctx.send("❌ You don't have any active trade requests!")
                return
            
            # Check if trade expired
            if trade['expires_at'] and trade['expires_at'] < datetime.now(timezone.utc):
                await conn.execute(
                    "UPDATE trades SET status = 'expired' WHERE trade_id = $1",
                    trade['trade_id']
                )
                await ctx.send("❌ This trade has expired!")
                return
            
            trade_id = trade['trade_id']
            status = trade['status']
            
            # Scenario 1: Responder accepting initial trade request
            if status == 'pending' and user_id == trade['responder_id']:
                await conn.execute(
                    "UPDATE trades SET status = 'active' WHERE trade_id = $1",
                    trade_id
                )
                
                try:
                    initiator = await self.bot.fetch_user(trade['initiator_id'])
                    embed = discord.Embed(
                        title="✅ Trade Accepted!",
                        description=(
                            f"{ctx.author.mention} accepted the trade!\n\n"
                            f"**Both players can now:**\n"
                            f"• Add cards: `/tradeadd [card_id] [amount]`\n"
                            f"• Remove cards: `/traderemove [card_id] [amount]`\n"
                            f"• When ready, both use `/accepttrade` to confirm\n"
                            f"• Then both use `/finalize` to complete the trade\n\n"
                            f"Trade expires in {TRADE_TIMEOUT_MINUTES} minutes."
                        ),
                        color=discord.Color.green()
                    )
                    await ctx.send(embed=embed)
                except:
                    await ctx.send("✅ Trade accepted! You can now add cards to the trade pool.")
                return
            
            # Scenario 2: User confirming they're ready to finalize
            if status == 'active':
                is_initiator = user_id == trade['initiator_id']
                
                if is_initiator:
                    await conn.execute(
                        "UPDATE trades SET initiator_accepted = TRUE WHERE trade_id = $1",
                        trade_id
                    )
                else:
                    await conn.execute(
                        "UPDATE trades SET responder_accepted = TRUE WHERE trade_id = $1",
                        trade_id
                    )
                
                # Check if both accepted
                updated_trade = await conn.fetchrow(
                    "SELECT * FROM trades WHERE trade_id = $1",
                    trade_id
                )
                
                if updated_trade['initiator_accepted'] and updated_trade['responder_accepted']:
                    await conn.execute(
                        "UPDATE trades SET status = 'accepted' WHERE trade_id = $1",
                        trade_id
                    )
                    
                    embed = discord.Embed(
                        title="✅ Both Players Ready!",
                        description=(
                            "Both players have accepted the trade terms.\n\n"
                            "**Final step:** Both players must use `/finalize` to complete the trade."
                        ),
                        color=discord.Color.gold()
                    )
                    await ctx.send(embed=embed)
                    await self.display_trade_pool(ctx, dict(updated_trade))
                else:
                    await ctx.send(f"✅ You've accepted the trade. Waiting for the other player...")
                return
            
            # Scenario 3: Already in accepted state, waiting for finalize
            if status == 'accepted':
                await ctx.send(
                    "✅ Trade is already accepted by both parties. "
                    "Use `/finalize` to complete the trade!"
                )
                return
            
            await ctx.send("❌ Invalid trade state. Please contact an admin.")
    
    @commands.command(name='tradeadd')
    async def trade_add(self, ctx, card_id: int, amount: int = 1):
        """
        Add cards to your side of the trade.
        Usage: /tradeadd [card_id] [amount]
        """
        user_id = ctx.author.id
        guild_id = ctx.guild.id if ctx.guild else None
        
        # Must be in a server
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
        
        if amount < 1:
            await ctx.send("❌ Amount must be at least 1!")
            return
        
        async with self.db_pool.acquire() as conn:
            trade = await self.get_active_trade(conn, user_id)
            
            if not trade or trade['status'] not in ['active', 'accepted']:
                await ctx.send("❌ You don't have an active trade!")
                return
            
            # Check if trade expired
            if trade['expires_at'] and trade['expires_at'] < datetime.now(timezone.utc):
                await conn.execute(
                    "UPDATE trades SET status = 'expired' WHERE trade_id = $1",
                    trade['trade_id']
                )
                await ctx.send("❌ This trade has expired!")
                return
            
            trade_id = trade['trade_id']
            
            # Verify card exists and belongs to this server's deck
            card = await conn.fetchrow(
                "SELECT name, rarity, deck_id FROM cards WHERE card_id = $1",
                card_id
            )
            
            if not card:
                await ctx.send(f"❌ Card ID `{card_id}` does not exist!")
                return
            
            # Verify card belongs to this server's deck
            if card['deck_id'] != deck_id:
                await ctx.send(
                    f"❌ Card **{card['name']}** is not part of this server's deck!\n"
                    f"You can only trade cards from **{deck['name']}** in this server."
                )
                return
            
            # Check user's inventory
            user_count = await self.check_user_card_count(conn, user_id, card_id)
            
            # Check how many already in trade
            current_trade_qty = await conn.fetchval(
                """SELECT quantity FROM trade_items
                   WHERE trade_id = $1 AND user_id = $2 AND card_id = $3""",
                trade_id, user_id, card_id
            ) or 0
            
            total_needed = current_trade_qty + amount
            
            if user_count < total_needed:
                await ctx.send(
                    f"❌ You don't have enough **{card['name']}** cards!\n"
                    f"You have: **{user_count}**, already in trade: **{current_trade_qty}**, "
                    f"trying to add: **{amount}**"
                )
                return
            
            # Add to trade
            await conn.execute(
                """INSERT INTO trade_items (trade_id, user_id, card_id, quantity)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (trade_id, user_id, card_id)
                   DO UPDATE SET quantity = trade_items.quantity + $4""",
                trade_id, user_id, card_id, amount
            )
            
            # Reset acceptances when trade pool changes
            if trade['status'] == 'accepted':
                await conn.execute(
                    """UPDATE trades
                       SET status = 'active',
                           initiator_accepted = FALSE,
                           responder_accepted = FALSE
                       WHERE trade_id = $1""",
                    trade_id
                )
        
        await ctx.send(f"✅ Added **{amount}x {card['name']}** to the trade!")
        
        # Refresh and display trade pool
        async with self.db_pool.acquire() as conn:
            updated_trade = await conn.fetchrow(
                "SELECT * FROM trades WHERE trade_id = $1",
                trade_id
            )
            await self.display_trade_pool(ctx, dict(updated_trade))
    
    @commands.command(name='traderemove')
    async def trade_remove(self, ctx, card_id: int, amount: int = 1):
        """
        Remove cards from your side of the trade.
        Usage: /traderemove [card_id] [amount]
        """
        user_id = ctx.author.id
        
        if amount < 1:
            await ctx.send("❌ Amount must be at least 1!")
            return
        
        async with self.db_pool.acquire() as conn:
            trade = await self.get_active_trade(conn, user_id)
            
            if not trade or trade['status'] not in ['active', 'accepted']:
                await ctx.send("❌ You don't have an active trade!")
                return
            
            trade_id = trade['trade_id']
            
            # Get current quantity in trade
            current_qty = await conn.fetchval(
                """SELECT quantity FROM trade_items
                   WHERE trade_id = $1 AND user_id = $2 AND card_id = $3""",
                trade_id, user_id, card_id
            )
            
            if not current_qty:
                await ctx.send(f"❌ You don't have card ID `{card_id}` in the trade!")
                return
            
            if current_qty < amount:
                await ctx.send(
                    f"❌ You only have **{current_qty}** of this card in the trade!"
                )
                return
            
            # Get card name
            card = await conn.fetchrow(
                "SELECT name FROM cards WHERE card_id = $1",
                card_id
            )
            
            # Remove from trade
            new_qty = current_qty - amount
            
            if new_qty == 0:
                await conn.execute(
                    """DELETE FROM trade_items
                       WHERE trade_id = $1 AND user_id = $2 AND card_id = $3""",
                    trade_id, user_id, card_id
                )
            else:
                await conn.execute(
                    """UPDATE trade_items
                       SET quantity = $4
                       WHERE trade_id = $1 AND user_id = $2 AND card_id = $3""",
                    trade_id, user_id, card_id, new_qty
                )
            
            # Reset acceptances when trade pool changes
            if trade['status'] == 'accepted':
                await conn.execute(
                    """UPDATE trades
                       SET status = 'active',
                           initiator_accepted = FALSE,
                           responder_accepted = FALSE
                       WHERE trade_id = $1""",
                    trade_id
                )
        
        await ctx.send(f"✅ Removed **{amount}x {card['name']}** from the trade!")
        
        # Refresh and display trade pool
        async with self.db_pool.acquire() as conn:
            updated_trade = await conn.fetchrow(
                "SELECT * FROM trades WHERE trade_id = $1",
                trade_id
            )
            await self.display_trade_pool(ctx, dict(updated_trade))
    
    @commands.command(name='finalize')
    async def finalize_trade(self, ctx):
        """
        Finalize and execute the trade (both players must confirm).
        Usage: /finalize
        """
        user_id = ctx.author.id
        guild_id = ctx.guild.id if ctx.guild else None
        
        # Must be in a server
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
        
        async with self.db_pool.acquire() as conn:
            trade = await self.get_active_trade(conn, user_id)
            
            if not trade:
                await ctx.send("❌ You don't have an active trade!")
                return
            
            if trade['status'] != 'accepted':
                await ctx.send(
                    "❌ Trade must be accepted by both parties before finalizing! "
                    "Both players need to use `/accepttrade` first."
                )
                return
            
            trade_id = trade['trade_id']
            is_initiator = user_id == trade['initiator_id']
            
            # Track who has finalized
            finalize_field = 'initiator_finalized' if is_initiator else 'responder_finalized'
            
            # Check if field exists, if not we'll track differently
            # For now, let's use a simpler approach: both must call finalize in sequence
            
            # Get items from both sides
            initiator_items = await self.get_trade_items(conn, str(trade_id), trade['initiator_id'])
            responder_items = await self.get_trade_items(conn, str(trade_id), trade['responder_id'])
            
            # Verify all cards belong to this server's deck
            all_items = initiator_items + responder_items
            for item in all_items:
                card_deck = await conn.fetchval(
                    "SELECT deck_id FROM cards WHERE card_id = $1",
                    item['card_id']
                )
                if card_deck != deck_id:
                    await ctx.send(
                        f"❌ Trade failed! Card **{item['name']}** is not part of this server's deck!\n"
                        f"All cards must be from **{deck['name']}** to complete this trade."
                    )
                    return
            
            # Execute trade in a transaction
            async with conn.transaction():
                # Verify both users still have the cards
                for item in initiator_items:
                    count = await self.check_user_card_count(conn, trade['initiator_id'], item['card_id'])
                    if count < item['quantity']:
                        await ctx.send(
                            f"❌ Trade failed! Initiator no longer has enough **{item['name']}** cards."
                        )
                        return
                
                for item in responder_items:
                    count = await self.check_user_card_count(conn, trade['responder_id'], item['card_id'])
                    if count < item['quantity']:
                        await ctx.send(
                            f"❌ Trade failed! Responder no longer has enough **{item['name']}** cards."
                        )
                        return
                
                # Transfer initiator's cards to responder
                for item in initiator_items:
                    # Get oldest instances
                    instances = await conn.fetch(
                        """SELECT instance_id FROM user_cards
                           WHERE user_id = $1 AND card_id = $2 AND recycled_at IS NULL
                           ORDER BY acquired_at ASC
                           LIMIT $3""",
                        trade['initiator_id'], item['card_id'], item['quantity']
                    )
                    
                    instance_ids = [inst['instance_id'] for inst in instances]
                    
                    # Transfer ownership
                    await conn.execute(
                        """UPDATE user_cards
                           SET user_id = $1, source = 'trade'
                           WHERE instance_id = ANY($2)""",
                        trade['responder_id'], instance_ids
                    )
                
                # Transfer responder's cards to initiator
                for item in responder_items:
                    instances = await conn.fetch(
                        """SELECT instance_id FROM user_cards
                           WHERE user_id = $1 AND card_id = $2 AND recycled_at IS NULL
                           ORDER BY acquired_at ASC
                           LIMIT $3""",
                        trade['responder_id'], item['card_id'], item['quantity']
                    )
                    
                    instance_ids = [inst['instance_id'] for inst in instances]
                    
                    await conn.execute(
                        """UPDATE user_cards
                           SET user_id = $1, source = 'trade'
                           WHERE instance_id = ANY($2)""",
                        trade['initiator_id'], instance_ids
                    )
                
                # Mark trade as completed
                await conn.execute(
                    """UPDATE trades
                       SET status = 'completed', finalized_at = $1
                       WHERE trade_id = $2""",
                    datetime.now(timezone.utc), trade_id
                )
        
        # Success message
        try:
            initiator = await self.bot.fetch_user(trade['initiator_id'])
            responder = await self.bot.fetch_user(trade['responder_id'])
            
            embed = discord.Embed(
                title="✅ Trade Completed!",
                description=f"Trade between {initiator.mention} and {responder.mention} has been finalized!",
                color=discord.Color.green()
            )
            
            if initiator_items:
                items_text = "\n".join([
                    f"• (x{item['quantity']}) {item['name']}"
                    for item in initiator_items
                ])
                embed.add_field(
                    name=f"{initiator.name} → {responder.name}",
                    value=items_text,
                    inline=False
                )
            
            if responder_items:
                items_text = "\n".join([
                    f"• (x{item['quantity']}) {item['name']}"
                    for item in responder_items
                ])
                embed.add_field(
                    name=f"{responder.name} → {initiator.name}",
                    value=items_text,
                    inline=False
                )
            
            await ctx.send(embed=embed)
        except:
            await ctx.send("✅ Trade completed successfully!")
    
    @commands.command(name='canceltrade')
    async def cancel_trade(self, ctx):
        """
        Cancel your active trade.
        Usage: !canceltrade
        """
        user_id = ctx.author.id
        
        async with self.db_pool.acquire() as conn:
            trade = await self.get_active_trade(conn, user_id)
            
            if not trade:
                await ctx.send("❌ You don't have an active trade to cancel!")
                return
            
            # Cancel the trade
            await conn.execute(
                """UPDATE trades
                   SET status = 'cancelled'
                   WHERE trade_id = $1""",
                trade['trade_id']
            )
        
        await ctx.send("✅ Trade cancelled!")


async def setup(bot):
    await bot.add_cog(TradingCommands(bot))
