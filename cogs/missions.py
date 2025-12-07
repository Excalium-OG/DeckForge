import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncpg
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import math

RARITY_HIERARCHY = ['Common', 'Uncommon', 'Exceptional', 'Rare', 'Epic', 'Legendary', 'Mythic']

RARITY_WEIGHTS = {
    'Common': 35,
    'Uncommon': 25,
    'Exceptional': 18,
    'Rare': 12,
    'Epic': 6,
    'Legendary': 3,
    'Mythic': 1
}

RARITY_COLORS = {
    'Common': 0x9CA3AF,
    'Uncommon': 0x10B981,
    'Exceptional': 0x3B82F6,
    'Rare': 0x8B5CF6,
    'Epic': 0xA855F7,
    'Legendary': 0xF59E0B,
    'Mythic': 0xEF4444
}

class MissionCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_pool: asyncpg.Pool = bot.db_pool
        self.activity_cache: Dict[int, Dict] = {}
        self.mission_check_loop.start()
        self.mission_lifecycle_loop.start()

    def cog_unload(self):
        self.mission_check_loop.cancel()
        self.mission_lifecycle_loop.cancel()

    @tasks.loop(minutes=10)
    async def mission_check_loop(self):
        """Check activity levels and spawn missions hourly"""
        try:
            await self.check_and_spawn_missions()
        except Exception as e:
            print(f"Mission check loop error: {e}")

    @mission_check_loop.before_loop
    async def before_mission_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def mission_lifecycle_loop(self):
        """Handle mission expiration and completion"""
        try:
            await self.process_mission_lifecycle()
        except Exception as e:
            print(f"Mission lifecycle loop error: {e}")

    @mission_lifecycle_loop.before_loop
    async def before_lifecycle_check(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Track message activity for mission spawning"""
        if message.author.bot or not message.guild:
            return
        
        guild_id = message.guild.id
        now = datetime.now(timezone.utc)
        
        if guild_id not in self.activity_cache:
            self.activity_cache[guild_id] = {
                'window_start': now,
                'message_count': 0,
                'unique_users': set()
            }
        
        cache = self.activity_cache[guild_id]
        
        if (now - cache['window_start']).total_seconds() > 3600:
            cache['window_start'] = now
            cache['message_count'] = 0
            cache['unique_users'] = set()
        
        cache['message_count'] += 1
        cache['unique_users'].add(message.author.id)

    async def check_and_spawn_missions(self):
        """Check all guilds for activity and spawn missions"""
        async with self.db_pool.acquire() as conn:
            for guild_id, activity in self.activity_cache.items():
                try:
                    if activity['message_count'] < 10 or len(activity['unique_users']) < 2:
                        continue
                    
                    settings = await conn.fetchrow(
                        """SELECT * FROM server_mission_settings WHERE guild_id = $1""",
                        guild_id
                    )
                    
                    if not settings or not settings['missions_enabled'] or not settings['mission_channel_id']:
                        continue
                    
                    last_spawn = settings['last_mission_spawn']
                    if last_spawn and (datetime.now(timezone.utc) - last_spawn).total_seconds() < 3600:
                        continue
                    
                    deck = await self.bot.get_server_deck(guild_id)
                    if not deck:
                        continue
                    
                    templates = await conn.fetch(
                        """SELECT * FROM mission_templates 
                           WHERE deck_id = $1 AND is_active = TRUE""",
                        deck['deck_id']
                    )
                    
                    if not templates:
                        continue
                    
                    await self.spawn_mission(conn, guild_id, deck['deck_id'], 
                                            settings['mission_channel_id'], templates, activity)
                    
                    activity['message_count'] = 0
                    activity['unique_users'] = set()
                    activity['window_start'] = datetime.now(timezone.utc)
                    
                except Exception as e:
                    print(f"Error checking missions for guild {guild_id}: {e}")

    async def spawn_mission(self, conn, guild_id: int, deck_id: int, 
                           channel_id: int, templates: List, activity: Dict):
        """Spawn a new mission in the guild"""
        template = random.choice(templates)
        
        activity_bonus = min(activity['message_count'] / 50, 1.0)
        rarity_weights = RARITY_WEIGHTS.copy()
        for rarity in ['Epic', 'Legendary', 'Mythic']:
            rarity_weights[rarity] = int(rarity_weights[rarity] * (1 + activity_bonus))
        
        total_weight = sum(rarity_weights.values())
        roll = random.uniform(0, total_weight)
        cumulative = 0
        selected_rarity = 'Common'
        for rarity in RARITY_HIERARCHY:
            cumulative += rarity_weights[rarity]
            if roll <= cumulative:
                selected_rarity = rarity
                break
        
        scaling = await conn.fetchrow(
            """SELECT * FROM mission_rarity_scaling 
               WHERE mission_template_id = $1 AND rarity = $2""",
            template['mission_template_id'], selected_rarity
        )
        
        if not scaling:
            return
        
        variance = template['variance_pct'] / 100.0
        
        base_req = template['min_value_base'] * scaling['requirement_multiplier']
        req_variance = base_req * random.uniform(-variance, variance)
        requirement_rolled = max(1, base_req + req_variance)
        
        base_reward = template['reward_base'] * scaling['reward_multiplier']
        reward_variance = base_reward * random.uniform(-variance, variance)
        reward_rolled = max(1, int(base_reward + reward_variance))
        
        base_duration = template['duration_base_hours'] * scaling['duration_multiplier']
        dur_variance = base_duration * random.uniform(-variance, variance)
        duration_rolled = max(1, int(base_duration + dur_variance))
        
        now = datetime.now(timezone.utc)
        reaction_expires = now + timedelta(minutes=20)
        
        result = await conn.fetchrow(
            """INSERT INTO active_missions 
               (mission_template_id, guild_id, deck_id, channel_id, spawned_at,
                reaction_expires_at, status, rarity_rolled, requirement_rolled,
                reward_rolled, duration_rolled_hours)
               VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, $8, $9, $10)
               RETURNING active_mission_id""",
            template['mission_template_id'], guild_id, deck_id, channel_id,
            now, reaction_expires, selected_rarity, requirement_rolled,
            reward_rolled, duration_rolled
        )
        
        mission_id = result['active_mission_id']
        
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        
        acceptance_cost = int(reward_rolled * 0.05)
        
        all_scaling = await conn.fetch(
            """SELECT rarity, success_rate FROM mission_rarity_scaling 
               WHERE mission_template_id = $1
               ORDER BY CASE rarity 
                   WHEN 'Common' THEN 1 WHEN 'Uncommon' THEN 2 
                   WHEN 'Exceptional' THEN 3 WHEN 'Rare' THEN 4 
                   WHEN 'Epic' THEN 5 WHEN 'Legendary' THEN 6 
                   WHEN 'Mythic' THEN 7 END""",
            template['mission_template_id']
        )
        
        success_rates = " | ".join([f"{r['rarity'][:3]} {int(r['success_rate'])}%" for r in all_scaling])
        
        embed = discord.Embed(
            title=f"🚀 Mission: {template['name']} [{selected_rarity.upper()}]",
            description=template['description'] or "Complete this mission to earn credits!",
            color=RARITY_COLORS.get(selected_rarity, 0x667EEA)
        )
        
        embed.add_field(
            name="📋 Requirement",
            value=f"**{template['requirement_field']}** >= {requirement_rolled:,.0f}",
            inline=True
        )
        
        embed.add_field(
            name="💰 Reward",
            value=f"**{reward_rolled:,}** credits\n(Cost: {acceptance_cost} cr)",
            inline=True
        )
        
        embed.add_field(
            name="⏱️ Duration",
            value=f"**{duration_rolled}** hours",
            inline=True
        )
        
        embed.add_field(
            name="📊 Success Rates by Card Rarity",
            value=success_rates,
            inline=False
        )
        
        embed.set_footer(text=f"React with ✅ within 20 minutes to accept! | Mission #{mission_id}")
        embed.timestamp = now
        
        try:
            message = await channel.send(embed=embed)
            await message.add_reaction("✅")
            
            await conn.execute(
                "UPDATE active_missions SET message_id = $1 WHERE active_mission_id = $2",
                message.id, mission_id
            )
            
            await conn.execute(
                """UPDATE server_mission_settings 
                   SET last_mission_spawn = $1 WHERE guild_id = $2""",
                now, guild_id
            )
            
        except Exception as e:
            print(f"Error posting mission embed: {e}")
            await conn.execute(
                "UPDATE active_missions SET status = 'expired' WHERE active_mission_id = $1",
                mission_id
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Handle mission acceptance via reactions"""
        if payload.user_id == self.bot.user.id:
            return
        
        if str(payload.emoji) != "✅":
            return
        
        async with self.db_pool.acquire() as conn:
            mission = await conn.fetchrow(
                """SELECT am.*, mt.name as template_name, mt.requirement_field
                   FROM active_missions am
                   JOIN mission_templates mt ON am.mission_template_id = mt.mission_template_id
                   WHERE am.message_id = $1 AND am.status = 'pending'""",
                payload.message_id
            )
            
            if not mission:
                return
            
            now = datetime.now(timezone.utc)
            if mission['reaction_expires_at'] and now > mission['reaction_expires_at']:
                return
            
            if mission['accepted_by']:
                return
            
            cooldown = await conn.fetchrow(
                """SELECT last_accept_time FROM user_mission_cooldowns 
                   WHERE user_id = $1 AND guild_id = $2""",
                payload.user_id, payload.guild_id
            )
            
            if cooldown:
                time_since = (now - cooldown['last_accept_time']).total_seconds()
                if time_since < 14400:
                    remaining = int((14400 - time_since) / 60)
                    try:
                        user = self.bot.get_user(payload.user_id)
                        if user:
                            await user.send(f"❌ You're on cooldown! Wait {remaining} more minutes before accepting another mission.")
                    except:
                        pass
                    return
            
            player = await conn.fetchrow(
                "SELECT credits FROM players WHERE user_id = $1",
                payload.user_id
            )
            
            acceptance_cost = int(mission['reward_rolled'] * 0.05)
            
            if not player or player['credits'] < acceptance_cost:
                try:
                    user = self.bot.get_user(payload.user_id)
                    if user:
                        await user.send(f"❌ You need {acceptance_cost} credits to accept this mission!")
                except:
                    pass
                return
            
            has_qualifying_card = await conn.fetchval(
                """SELECT COUNT(*) FROM user_cards uc
                   JOIN cards c ON uc.card_id = c.card_id
                   JOIN card_template_fields ctf ON c.card_id = ctf.card_id
                   JOIN card_templates ct ON ctf.template_id = ct.template_id
                   WHERE uc.user_id = $1 AND uc.recycled_at IS NULL
                   AND ct.field_name = $2 AND ct.field_type = 'number'
                   AND CAST(ctf.field_value AS FLOAT) >= $3""",
                payload.user_id, mission['requirement_field'], mission['requirement_rolled']
            )
            
            if not has_qualifying_card:
                try:
                    user = self.bot.get_user(payload.user_id)
                    if user:
                        await user.send(f"❌ You don't have a card with {mission['requirement_field']} >= {mission['requirement_rolled']:,.0f}!")
                except:
                    pass
                return
            
            mission_expires = now + timedelta(days=1)
            
            async with conn.transaction():
                await conn.execute(
                    "UPDATE players SET credits = credits - $1 WHERE user_id = $2",
                    acceptance_cost, payload.user_id
                )
                
                await conn.execute(
                    """UPDATE active_missions 
                       SET accepted_by = $1, accepted_at = $2, status = 'pending',
                           mission_expires_at = $3
                       WHERE active_mission_id = $4""",
                    payload.user_id, now, mission_expires, mission['active_mission_id']
                )
                
                await conn.execute(
                    """INSERT INTO user_missions 
                       (user_id, guild_id, active_mission_id, status, acceptance_cost, accepted_at)
                       VALUES ($1, $2, $3, 'accepted', $4, $5)""",
                    payload.user_id, payload.guild_id, mission['active_mission_id'], 
                    acceptance_cost, now
                )
                
                await conn.execute(
                    """INSERT INTO user_mission_cooldowns (user_id, guild_id, last_accept_time)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (user_id, guild_id) 
                       DO UPDATE SET last_accept_time = $3""",
                    payload.user_id, payload.guild_id, now
                )
            
            try:
                channel = self.bot.get_channel(payload.channel_id)
                if channel:
                    message = await channel.fetch_message(payload.message_id)
                    user = self.bot.get_user(payload.user_id)
                    
                    embed = message.embeds[0] if message.embeds else None
                    if embed:
                        embed.color = 0x10B981
                        embed.set_footer(text=f"✅ Accepted by {user.display_name if user else 'Unknown'} | Use /startmission to begin!")
                        await message.edit(embed=embed)
                        await message.clear_reactions()
            except Exception as e:
                print(f"Error updating mission message: {e}")
            
            try:
                user = self.bot.get_user(payload.user_id)
                if user:
                    await user.send(
                        f"✅ **Mission Accepted!** {mission['template_name']} [{mission['rarity_rolled']}]\n"
                        f"💰 Cost: {acceptance_cost} credits deducted\n"
                        f"📋 Use `/startmission` within 24 hours to begin the mission!\n"
                        f"⏱️ Mission duration: {mission['duration_rolled_hours']} hours"
                    )
            except:
                pass

    @commands.hybrid_command(name='startmission', description="Start an accepted mission with a qualifying card")
    @app_commands.describe(card_name="The card to use for the mission")
    async def start_mission(self, ctx, *, card_name: str):
        """Start an accepted mission using a qualifying card"""
        if ctx.interaction:
            await ctx.defer()
        
        user_id = ctx.author.id
        guild_id = ctx.guild.id if ctx.guild else None
        
        if not guild_id:
            await ctx.send("❌ This command can only be used in a server!")
            return
        
        async with self.db_pool.acquire() as conn:
            mission = await conn.fetchrow(
                """SELECT am.*, mt.name as template_name, mt.requirement_field,
                          mrs.success_rate
                   FROM active_missions am
                   JOIN mission_templates mt ON am.mission_template_id = mt.mission_template_id
                   JOIN mission_rarity_scaling mrs ON mt.mission_template_id = mrs.mission_template_id
                   WHERE am.accepted_by = $1 AND am.guild_id = $2 AND am.status = 'pending'
                   AND mrs.rarity = am.rarity_rolled
                   ORDER BY am.accepted_at DESC
                   LIMIT 1""",
                user_id, guild_id
            )
            
            if not mission:
                await ctx.send("❌ You don't have any pending missions! Accept a mission first.")
                return
            
            qualifying_card = await conn.fetchrow(
                """SELECT uc.instance_id, uc.card_id, c.name, c.rarity,
                          uc.merge_level, ctf.field_value
                   FROM user_cards uc
                   JOIN cards c ON uc.card_id = c.card_id
                   JOIN card_template_fields ctf ON c.card_id = ctf.card_id
                   JOIN card_templates ct ON ctf.template_id = ct.template_id
                   WHERE uc.user_id = $1 AND uc.recycled_at IS NULL
                   AND LOWER(c.name) = LOWER($2)
                   AND ct.field_name = $3 AND ct.field_type = 'number'
                   AND CAST(ctf.field_value AS FLOAT) >= $4
                   ORDER BY uc.merge_level DESC
                   LIMIT 1""",
                user_id, card_name, mission['requirement_field'], mission['requirement_rolled']
            )
            
            if not qualifying_card:
                await ctx.send(
                    f"❌ **{card_name}** doesn't qualify for this mission!\n"
                    f"Need: {mission['requirement_field']} >= {mission['requirement_rolled']:,.0f}"
                )
                return
            
            now = datetime.now(timezone.utc)
            mission_end = now + timedelta(hours=mission['duration_rolled_hours'])
            
            card_rarity = qualifying_card['rarity']
            scaling = await conn.fetchrow(
                """SELECT success_rate FROM mission_rarity_scaling 
                   WHERE mission_template_id = $1 AND rarity = $2""",
                mission['mission_template_id'], card_rarity
            )
            
            base_success_rate = scaling['success_rate'] if scaling else 50.0
            merge_bonus = qualifying_card['merge_level'] * 5
            final_success_rate = min(99, base_success_rate + merge_bonus)
            
            success_roll = random.uniform(0, 100)
            will_succeed = success_roll <= final_success_rate
            
            async with conn.transaction():
                await conn.execute(
                    """UPDATE active_missions 
                       SET status = 'active', started_at = $1, 
                           mission_expires_at = $2, card_instance_id = $3,
                           success_roll = $4
                       WHERE active_mission_id = $5""",
                    now, mission_end, qualifying_card['instance_id'],
                    success_roll, mission['active_mission_id']
                )
                
                await conn.execute(
                    """UPDATE user_missions 
                       SET status = 'accepted', started_at = $1, card_instance_id = $2
                       WHERE active_mission_id = $3 AND user_id = $4""",
                    now, qualifying_card['instance_id'], mission['active_mission_id'], user_id
                )
            
            embed = discord.Embed(
                title=f"🚀 Mission Started!",
                description=f"**{mission['template_name']}** [{mission['rarity_rolled']}]",
                color=0x667EEA
            )
            
            embed.add_field(
                name="Card Used",
                value=f"**{qualifying_card['name']}** [{card_rarity}]" + 
                      (f" ★{qualifying_card['merge_level']}" if qualifying_card['merge_level'] > 0 else ""),
                inline=True
            )
            
            embed.add_field(
                name="Success Chance",
                value=f"**{final_success_rate:.0f}%**" + 
                      (f" (+{merge_bonus}% merge bonus)" if merge_bonus > 0 else ""),
                inline=True
            )
            
            embed.add_field(
                name="Completion Time",
                value=f"<t:{int(mission_end.timestamp())}:R>",
                inline=True
            )
            
            embed.set_footer(text=f"Reward on success: {mission['reward_rolled']:,} credits")
            
            await ctx.send(embed=embed)

    @start_mission.autocomplete('card_name')
    async def start_mission_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for card selection"""
        user_id = interaction.user.id
        
        async with self.db_pool.acquire() as conn:
            mission = await conn.fetchrow(
                """SELECT am.*, mt.requirement_field
                   FROM active_missions am
                   JOIN mission_templates mt ON am.mission_template_id = mt.mission_template_id
                   WHERE am.accepted_by = $1 AND am.status = 'pending'
                   ORDER BY am.accepted_at DESC
                   LIMIT 1""",
                user_id
            )
            
            if not mission:
                return []
            
            cards = await conn.fetch(
                """SELECT DISTINCT c.name, c.rarity, uc.merge_level, ctf.field_value
                   FROM user_cards uc
                   JOIN cards c ON uc.card_id = c.card_id
                   JOIN card_template_fields ctf ON c.card_id = ctf.card_id
                   JOIN card_templates ct ON ctf.template_id = ct.template_id
                   WHERE uc.user_id = $1 AND uc.recycled_at IS NULL
                   AND ct.field_name = $2 AND ct.field_type = 'number'
                   AND CAST(ctf.field_value AS FLOAT) >= $3
                   AND LOWER(c.name) LIKE LOWER($4)
                   ORDER BY uc.merge_level DESC, c.name
                   LIMIT 25""",
                user_id, mission['requirement_field'], mission['requirement_rolled'],
                f"%{current}%"
            )
            
            choices = []
            for card in cards:
                merge_display = f" ★{card['merge_level']}" if card['merge_level'] > 0 else ""
                display = f"{card['name']}{merge_display} [{card['rarity']}] ({float(card['field_value']):,.0f})"
                choices.append(app_commands.Choice(name=display[:100], value=card['name']))
            
            return choices

    async def process_mission_lifecycle(self):
        """Process mission completions and expirations"""
        now = datetime.now(timezone.utc)
        
        async with self.db_pool.acquire() as conn:
            expired_reactions = await conn.fetch(
                """SELECT * FROM active_missions 
                   WHERE status = 'pending' AND accepted_by IS NULL
                   AND reaction_expires_at < $1""",
                now
            )
            
            for mission in expired_reactions:
                await conn.execute(
                    "UPDATE active_missions SET status = 'expired' WHERE active_mission_id = $1",
                    mission['active_mission_id']
                )
            
            expired_starts = await conn.fetch(
                """SELECT * FROM active_missions 
                   WHERE status = 'pending' AND accepted_by IS NOT NULL
                   AND mission_expires_at < $1""",
                now
            )
            
            for mission in expired_starts:
                await conn.execute(
                    "UPDATE active_missions SET status = 'expired' WHERE active_mission_id = $1",
                    mission['active_mission_id']
                )
                await conn.execute(
                    "UPDATE user_missions SET status = 'expired' WHERE active_mission_id = $1",
                    mission['active_mission_id']
                )
            
            completed_missions = await conn.fetch(
                """SELECT am.*, mt.name as template_name, mrs.success_rate
                   FROM active_missions am
                   JOIN mission_templates mt ON am.mission_template_id = mt.mission_template_id
                   JOIN mission_rarity_scaling mrs ON mt.mission_template_id = mrs.mission_template_id
                   WHERE am.status = 'active' AND am.mission_expires_at < $1
                   AND mrs.rarity = am.rarity_rolled""",
                now
            )
            
            for mission in completed_missions:
                try:
                    uc = await conn.fetchrow(
                        "SELECT merge_level FROM user_cards WHERE instance_id = $1",
                        mission['card_instance_id']
                    )
                    merge_level = uc['merge_level'] if uc else 0
                    merge_bonus = merge_level * 5
                    final_success_rate = min(99, mission['success_rate'] + merge_bonus)
                    
                    success = mission['success_roll'] <= final_success_rate
                    
                    if success:
                        credits_earned = mission['reward_rolled']
                        credit_bonus = int(credits_earned * merge_level * 0.05)
                        total_credits = credits_earned + credit_bonus
                        
                        await conn.execute(
                            "UPDATE players SET credits = credits + $1 WHERE user_id = $2",
                            total_credits, mission['accepted_by']
                        )
                        
                        await conn.execute(
                            """UPDATE active_missions 
                               SET status = 'completed', completed_at = $1
                               WHERE active_mission_id = $2""",
                            now, mission['active_mission_id']
                        )
                        
                        await conn.execute(
                            """UPDATE user_missions 
                               SET status = 'completed', completed_at = $1, credits_earned = $2
                               WHERE active_mission_id = $3""",
                            now, total_credits, mission['active_mission_id']
                        )
                        
                        try:
                            user = self.bot.get_user(mission['accepted_by'])
                            if user:
                                await user.send(
                                    f"🎉 **Mission Complete!** {mission['template_name']}\n"
                                    f"💰 Earned: **{total_credits:,}** credits" +
                                    (f" (+{credit_bonus:,} merge bonus)" if credit_bonus > 0 else "")
                                )
                        except:
                            pass
                    else:
                        await conn.execute(
                            """UPDATE active_missions 
                               SET status = 'failed', completed_at = $1
                               WHERE active_mission_id = $2""",
                            now, mission['active_mission_id']
                        )
                        
                        await conn.execute(
                            """UPDATE user_missions 
                               SET status = 'failed', completed_at = $1
                               WHERE active_mission_id = $2""",
                            now, mission['active_mission_id']
                        )
                        
                        try:
                            user = self.bot.get_user(mission['accepted_by'])
                            if user:
                                await user.send(
                                    f"❌ **Mission Failed!** {mission['template_name']}\n"
                                    f"Better luck next time! The acceptance cost was lost."
                                )
                        except:
                            pass
                            
                except Exception as e:
                    print(f"Error processing mission {mission['active_mission_id']}: {e}")

    @commands.hybrid_command(name='mymissions', description="View your active and pending missions")
    async def my_missions(self, ctx):
        """View your active missions"""
        if ctx.interaction:
            await ctx.defer()
        
        user_id = ctx.author.id
        
        async with self.db_pool.acquire() as conn:
            missions = await conn.fetch(
                """SELECT am.*, mt.name as template_name, mt.requirement_field,
                          c.name as card_name
                   FROM active_missions am
                   JOIN mission_templates mt ON am.mission_template_id = mt.mission_template_id
                   LEFT JOIN cards c ON am.card_instance_id IS NOT NULL 
                        AND EXISTS (SELECT 1 FROM user_cards uc WHERE uc.instance_id = am.card_instance_id AND uc.card_id = c.card_id)
                   WHERE am.accepted_by = $1 AND am.status IN ('pending', 'active')
                   ORDER BY am.status DESC, am.accepted_at DESC
                   LIMIT 10""",
                user_id
            )
            
            if not missions:
                await ctx.send("📋 You don't have any active missions. React to a mission embed to accept one!")
                return
            
            embed = discord.Embed(
                title="📋 Your Missions",
                color=0x667EEA
            )
            
            for m in missions:
                if m['status'] == 'pending':
                    status = "⏳ Pending (use /startmission)"
                    expires = m['mission_expires_at']
                else:
                    status = "🚀 Active"
                    expires = m['mission_expires_at']
                
                value = f"**Status:** {status}\n"
                value += f"**Rarity:** {m['rarity_rolled']}\n"
                value += f"**Reward:** {m['reward_rolled']:,} credits\n"
                if expires:
                    value += f"**Expires:** <t:{int(expires.timestamp())}:R>"
                
                embed.add_field(
                    name=f"{m['template_name']}",
                    value=value,
                    inline=False
                )
            
            await ctx.send(embed=embed)

    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        admin_ids = getattr(self.bot, 'admin_ids', [])
        return user_id in admin_ids or user_id == self.bot.owner_id

    @commands.command(name='sendmission')
    async def send_mission(self, ctx):
        """
        [ADMIN] Manually trigger a mission spawn for testing.
        Usage: !sendmission
        """
        if not self.is_admin(ctx.author.id):
            await ctx.send("❌ This command is only available to DeckForge admins.")
            return
        
        guild_id = ctx.guild.id
        
        async with self.db_pool.acquire() as conn:
            settings = await conn.fetchrow(
                """SELECT * FROM server_mission_settings WHERE guild_id = $1""",
                guild_id
            )
            
            if not settings or not settings['mission_channel_id']:
                await ctx.send("❌ No mission channel configured for this server. Set one via the web portal.")
                return
            
            if not settings['missions_enabled']:
                await ctx.send("❌ Missions are disabled for this server.")
                return
            
            deck = await conn.fetchrow(
                """SELECT d.deck_id FROM decks d
                   JOIN server_decks sd ON d.deck_id = sd.deck_id
                   WHERE sd.guild_id = $1""",
                guild_id
            )
            
            if not deck:
                await ctx.send("❌ No deck assigned to this server.")
                return
            
            templates = await conn.fetch(
                """SELECT mt.* FROM mission_templates mt
                   WHERE mt.deck_id = $1 AND mt.is_active = true""",
                deck['deck_id']
            )
            
            if not templates:
                await ctx.send("❌ No active mission templates found for this deck.")
                return
            
            template = random.choice(templates)
            
            scaling_rows = await conn.fetch(
                """SELECT * FROM mission_rarity_scaling 
                   WHERE mission_template_id = $1
                   ORDER BY CASE rarity 
                       WHEN 'Common' THEN 1 WHEN 'Uncommon' THEN 2
                       WHEN 'Exceptional' THEN 3 WHEN 'Rare' THEN 4
                       WHEN 'Epic' THEN 5 WHEN 'Legendary' THEN 6
                       WHEN 'Mythic' THEN 7 END""",
                template['mission_template_id']
            )
            
            if not scaling_rows:
                await ctx.send("❌ No rarity scaling configured for the selected mission template.")
                return
            
            total_weight = sum(RARITY_WEIGHTS.get(r['rarity'], 0) for r in scaling_rows)
            roll = random.uniform(0, total_weight)
            cumulative = 0
            chosen_rarity = None
            scaling = None
            
            for row in scaling_rows:
                cumulative += RARITY_WEIGHTS.get(row['rarity'], 0)
                if roll <= cumulative:
                    chosen_rarity = row['rarity']
                    scaling = row
                    break
            
            if not scaling:
                scaling = scaling_rows[0]
                chosen_rarity = scaling['rarity']
            
            base_req = template['min_value_base']
            base_reward = template['reward_base']
            base_duration = template['duration_base_hours']
            variance = template['variance_pct'] / 100.0
            
            req_mult = scaling['requirement_multiplier']
            reward_mult = scaling['reward_multiplier']
            duration_mult = scaling['duration_multiplier']
            
            requirement_rolled = int(base_req * req_mult * random.uniform(1 - variance, 1 + variance))
            reward_rolled = int(base_reward * reward_mult * random.uniform(1 - variance, 1 + variance))
            duration_rolled = max(1, int(base_duration * duration_mult))
            success_roll = random.randint(1, 100)
            
            now = datetime.now(timezone.utc)
            reaction_expires = now + timedelta(minutes=20)
            
            mission_id = await conn.fetchval(
                """INSERT INTO active_missions 
                   (guild_id, mission_template_id, deck_id, rarity_rolled, requirement_rolled,
                    reward_rolled, duration_rolled_hours, success_roll, spawned_at, 
                    reaction_expires_at, status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'pending')
                   RETURNING active_mission_id""",
                guild_id, template['mission_template_id'], deck['deck_id'], chosen_rarity,
                requirement_rolled, reward_rolled, duration_rolled, success_roll,
                now, reaction_expires
            )
        
        await ctx.send(f"✅ Mission spawned! Check <#{settings['mission_channel_id']}> for the mission embed.")
        await self.spawn_mission(guild_id, mission_id)

    @commands.command(name='checkchatactivity')
    async def check_chat_activity(self, ctx):
        """
        [ADMIN] Check observed chat activity and mission drop chances.
        Usage: !checkchatactivity
        """
        if not self.is_admin(ctx.author.id):
            await ctx.send("❌ This command is only available to DeckForge admins.")
            return
        
        guild_id = ctx.guild.id
        
        if guild_id not in self.activity_cache:
            await ctx.send("📊 No chat activity recorded yet for this server.")
            return
        
        cache = self.activity_cache[guild_id]
        message_count = cache['message_count']
        unique_users = len(cache['unique_users'])
        
        channels_seen = set()
        for member_id in cache['unique_users']:
            for channel in ctx.guild.text_channels:
                if channel.permissions_for(ctx.guild.get_member(member_id) or ctx.author).send_messages:
                    channels_seen.add(channel.id)
        
        channel_count = len(channels_seen) if channels_seen else 1
        
        total_weight = sum(RARITY_WEIGHTS.values())
        rarity_chances = []
        for rarity in RARITY_HIERARCHY:
            chance = (RARITY_WEIGHTS[rarity] / total_weight) * 100
            rarity_chances.append(f"{rarity} {chance:.0f}%")
        
        chances_str = ", ".join(rarity_chances)
        
        await ctx.send(
            f"📊 **Chat Activity Stats**\n"
            f"{message_count} messages from {unique_users} users observed.\n"
            f"**Mission drop chance based on rarity weights:** {chances_str}"
        )


async def setup(bot):
    await bot.add_cog(MissionCommands(bot))
