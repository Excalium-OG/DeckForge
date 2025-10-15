# DeckForge - Discord Trading Card Bot

## Overview

DeckForge is a Discord bot that implements a collectible rocket-themed trading card game. The bot enables users to collect cards through a time-gated drop system, view their collections, and interact with card information. The system is designed with a phased rollout approach, with Phase 1 focusing on core card collection mechanics and admin tools, while future phases will introduce gameplay mechanics, trading, and monetization features.

**Status**: Phase 1 Complete ✅ - Bot is production-ready and running

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Discord Bot Framework**: Built using discord.py with command extension (discord.ext.commands)
- **Command System**: Prefix-based commands using "!" as the command prefix
- **Bot Architecture**: Custom bot class (DeckForgeBot) extends commands.Bot to integrate database connection pooling
- **Code Organization**: Cog-based architecture to separate concerns:
  - `cogs/cards.py` - Core card collection and management commands
  - `cogs/future.py` - Placeholder commands for future features
  - `utils/card_helpers.py` - Shared utility functions for card operations

**Rationale**: The cog-based architecture provides modularity and maintainability, allowing features to be organized by domain and easily extended in future phases.

### Authentication & Authorization
- **Admin System**: Role-based access control using Discord user IDs
- **Admin Configuration**: Environment variable (`ADMIN_IDS`) stores comma-separated admin user IDs
- **Permission Checks**: `is_admin()` helper method validates user permissions before executing privileged commands
- **Bot Owner**: Automatic admin privileges for the bot owner (via discord.py's owner_id)

**Rationale**: Simple ID-based admin system is sufficient for Phase 1. Future phases may introduce more granular role-based permissions if needed.

### Data Layer
- **Database**: PostgreSQL for persistent storage
- **Connection Management**: asyncpg connection pooling (min_size=2, max_size=10, 60s timeout)
- **Async Operations**: All database operations use async/await pattern for non-blocking I/O
- **Schema Design**: Three core tables:
  1. `players` - User profiles, credits, and drop cooldown timestamps
  2. `cards` - Master card definitions with metadata and images
  3. `user_cards` - Individual card instances owned by players (uses UUID for unique identification)

**Rationale**: PostgreSQL provides ACID compliance for critical game data. Connection pooling prevents connection exhaustion under load. UUID-based card instances enable unique ownership and future trading mechanics.

### Core Game Mechanics
- **Drop System**: Time-gated card acquisition (2 random cards every 8 hours)
- **Cooldown Tracking**: Timestamp-based cooldown stored in `players.last_drop_ts`
- **Rarity System**: Seven-tier hierarchy (Common → Uncommon → Exceptional → Rare → Epic → Legendary → Mythic)
- **Card Sorting**: Cards displayed by rarity (ascending), then alphabetically by name
- **Instance-Based Ownership**: Each dropped card creates a unique instance with UUID

**Rationale**: Time-gated drops encourage regular engagement without overwhelming users. UUID instances enable future features like trading, recycling, and unique card histories.

### Image & Asset Management
- **Card Images**: Stored as URLs (image_url field in cards table)
- **Image Upload**: Admin commands accept Discord message attachments
- **Image Validation**: Helper function validates attachment format and size
- **Display**: Card embeds use Discord's embed system to display images

**Rationale**: URL-based storage is flexible for various hosting solutions. Phase 1 likely stores URLs pointing to Discord CDN or external hosting.

### Command Design Patterns
- **Help System**: Uses discord.py's default help command
- **Error Handling**: Validation checks before database operations (rarity validation, UUID format, ownership checks)
- **User Feedback**: Rich embeds for card displays, plain text for errors and confirmations
- **Future-Proofing**: Placeholder commands (`!recycle`, `!buycredits`, `!launch`) prepared for Phase 2

**Rationale**: Clear separation between implemented and planned features helps manage user expectations while providing a roadmap for development.

## External Dependencies

### Required Services
- **Discord API**: Primary platform integration via discord.py library
  - Requires bot token (`DECKFORGE_BOT_TOKEN`)
  - Requires MESSAGE CONTENT INTENT privileged intent
  - Optional: SERVER MEMBERS INTENT for member information
  
- **PostgreSQL Database**: Data persistence layer
  - Connection string via `DATABASE_URL` environment variable
  - Requires asyncpg driver for async database operations

### Python Libraries
- **discord.py**: Discord bot framework and API wrapper
- **asyncpg**: Async PostgreSQL driver for database operations
- **python-dotenv**: Environment variable management

### Environment Configuration
- `DECKFORGE_BOT_TOKEN` (required): Discord bot authentication token - **Configured** ✅
- `DATABASE_URL` (required): PostgreSQL connection string - **Auto-configured by Replit** ✅
- `ADMIN_IDS` (optional): Comma-separated Discord user IDs for admin privileges - **Can be configured by user**

**Note**: DECKFORGE_BOT_TOKEN is used (not DISCORD_BOT_TOKEN) to allow multiple bots in the same Replit environment.

### Future Integrations (Planned)
- **Stripe API**: Payment processing for credit purchases (Phase 2)
- **Image Storage Service**: Dedicated storage for card images if needed (current implementation uses Discord CDN or external URLs)

### Discord Bot Permissions
- Send Messages
- Embed Links
- Attach Files
- Read Message History
- Add Reactions
- Use External Emojis (optional)
- Use Slash Commands (future enhancement)