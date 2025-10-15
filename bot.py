"""
DeckForge - Discord Trading Card Bot
Main bot file with database connection pooling and cog loading
"""
import discord
from discord.ext import commands
import asyncpg
import os
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()

# Bot configuration
DISCORD_TOKEN = os.getenv('DECKFORGE_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
COMMAND_PREFIX = '!'

# Admin IDs (can be configured via environment variable)
ADMIN_IDS = []
admin_ids_env = os.getenv('ADMIN_IDS', '')
if admin_ids_env:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_env.split(',') if id.strip()]


class DeckForgeBot(commands.Bot):
    """Custom bot class with database pool"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(
            command_prefix=COMMAND_PREFIX,
            intents=intents,
            help_command=commands.DefaultHelpCommand()
        )
        
        self.db_pool = None
        self.admin_ids = ADMIN_IDS
    
    async def setup_hook(self):
        """Setup database and load cogs"""
        # Create database connection pool
        self.db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        
        print("✅ Database connection pool created")
        
        # Run migrations
        await self.run_migrations()
        
        # Load cogs
        await self.load_extension('cogs.cards')
        await self.load_extension('cogs.future')
        print("✅ Loaded all cogs")
    
    async def run_migrations(self):
        """Run database migrations"""
        migration_file = 'db/migrations/0001_cardbot.sql'
        
        if not os.path.exists(migration_file):
            print(f"⚠️ Migration file not found: {migration_file}")
            return
        
        with open(migration_file, 'r') as f:
            migration_sql = f.read()
        
        async with self.db_pool.acquire() as conn:
            await conn.execute(migration_sql)
        
        print("✅ Database migrations completed")
    
    async def on_ready(self):
        """Called when bot is ready"""
        print(f"🚀 DeckForge bot is ready!")
        print(f"   Logged in as: {self.user.name} ({self.user.id})")
        print(f"   Command prefix: {COMMAND_PREFIX}")
        print(f"   Admin IDs: {self.admin_ids if self.admin_ids else 'None (only bot owner)'}")
        print(f"   Serving {len(self.guilds)} guild(s)")
        print("-" * 50)
    
    async def on_command_error(self, ctx, error):
        """Global error handler"""
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: `{error.param.name}`\nUse `!help {ctx.command}` for usage info.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Invalid argument: {str(error)}")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command!")
        else:
            await ctx.send(f"❌ An error occurred: {str(error)}")
            print(f"Error in command {ctx.command}: {error}")
    
    async def close(self):
        """Cleanup on shutdown"""
        if self.db_pool:
            await self.db_pool.close()
            print("✅ Database connection pool closed")
        await super().close()


async def main():
    """Main entry point"""
    # Check for Discord token
    if not DISCORD_TOKEN:
        print("❌ ERROR: DECKFORGE_BOT_TOKEN not found in environment variables!")
        print("Please set up your Discord bot token:")
        print("1. Go to https://discord.com/developers/applications")
        print("2. Create a new application or select existing one")
        print("3. Go to 'Bot' section and copy the token")
        print("4. Add DECKFORGE_BOT_TOKEN to your environment variables or .env file")
        return
    
    if not DATABASE_URL:
        print("❌ ERROR: DATABASE_URL not found in environment variables!")
        return
    
    # Create and run bot
    bot = DeckForgeBot()
    
    try:
        await bot.start(DISCORD_TOKEN)
    except KeyboardInterrupt:
        print("\n⚠️ Shutting down bot...")
        await bot.close()
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
