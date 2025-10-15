# DeckForge - Discord Trading Card Bot

## Overview

DeckForge is a Discord bot that implements a collectible rocket-themed trading card game. The bot enables users to collect cards through a time-gated drop system, view their collections, and interact with card information. The system is designed with a phased rollout approach, with Phase 1 focusing on core card collection mechanics and admin tools, while future phases will introduce gameplay mechanics, trading, and monetization features.

**Status**: Phase 2 Complete ✅ - Pack-based card system with inventory management and configurable drop rates

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Discord Bot Framework**: Built using discord.py with command extension (discord.ext.commands)
- **Command System**: Prefix-based commands using "!" as the command prefix
- **Bot Architecture**: Custom bot class (DeckForgeBot) extends commands.Bot to integrate database connection pooling
- **Code Organization**: Cog-based architecture to separate concerns:
  - `cogs/cards.py` - Card opening and management commands (!drop, !mycards, !cardinfo, !addcard)
  - `cogs/packs.py` - Pack inventory and claiming commands (!claimfreepack, !mypacks, trading placeholders)
  - `cogs/future.py` - Placeholder commands for future features
  - `utils/card_helpers.py` - Shared utility functions for card operations
  - `utils/pack_logic.py` - Pack type validation and rarity modifier calculations

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
- **Schema Design**: Six core tables:
  1. `players` - User profiles, credits, and pack claim cooldown timestamps
  2. `cards` - Master card definitions with metadata and images
  3. `user_cards` - Individual card instances owned by players (uses UUID for unique identification)
  4. `drop_rates` - Guild-specific rarity drop rate configuration (guild_id, rarity, percentage)
  5. `user_packs` - Pack inventory per user (user_id, pack_type, quantity) with 30 total pack limit
  6. `pack_trades` - Pack trading scaffolding (trade_id, sender_id, receiver_id, pack_type, quantity, status)

**Rationale**: PostgreSQL provides ACID compliance for critical game data. Connection pooling prevents connection exhaustion under load. UUID-based card instances enable unique ownership and future trading mechanics. Pack inventory system enables strategic collection gameplay.

### Core Game Mechanics

#### Pack System (Phase 2)
- **Pack Types**: Three tiers - Normal Pack, Booster Pack, Booster Pack+
- **Pack Acquisition**: 
  - Free Normal Pack every 8 hours via `!claimfreepack` (30 pack inventory limit)
  - Purchase packs with credits via `!buypack [amount] [pack_type]`
- **Pack Pricing**: Normal Pack (100 credits), Booster Pack (300 credits), Booster Pack+ (500 credits)
- **Pack Opening**: `!drop [amount] [pack_type]` opens packs to receive 2 cards per pack
- **Pack Inventory**: Maximum 30 total packs across all types per user
- **Rarity Modifiers**:
  - Normal Pack: Uses base drop rates
  - Booster Pack: 2x multiplier on Epic, Legendary, Mythic rates (normalized to 100%)
  - Booster Pack+: 3x multiplier on Epic, Legendary, Mythic rates (normalized to 100%)

#### Card System
- **Cooldown Tracking**: Timestamp-based cooldown stored in `players.last_drop_ts` (used for pack claiming)
- **Rarity System**: Seven-tier hierarchy (Common → Uncommon → Exceptional → Rare → Epic → Legendary → Mythic)
- **Drop Rates**: Configurable weighted probabilities per guild with validation (must sum to 100%)
- **Default Base Rates**: Common 40%, Uncommon 25%, Exceptional 15%, Rare 10%, Epic 6%, Legendary 3%, Mythic 1%
- **Card Sorting**: Cards displayed by rarity (ascending), then alphabetically by name
- **Instance-Based Ownership**: Each card from a pack creates a unique instance with UUID

**Rationale**: Pack-based system adds depth and strategy to collection. Booster packs provide progression incentive. Time-gated pack claiming encourages regular engagement without overwhelming users. UUID instances enable future features like trading, recycling, and unique card histories.

### Image & Asset Management
- **Card Images**: Stored as URLs (image_url field in cards table)
- **Image Upload**: Admin commands accept Discord message attachments
- **Image Validation**: Helper function validates attachment format and size
- **Display**: Card embeds use Discord's embed system to display images

**Rationale**: URL-based storage is flexible for various hosting solutions. Phase 1 likely stores URLs pointing to Discord CDN or external hosting.

### Command Design Patterns
- **Help System**: Custom help command that filters admin-only commands based on user permissions
  - Admin commands marked with [ADMIN] tag are hidden from non-admin users in help output
  - Admins see all commands; regular users only see commands they can use
- **Error Handling**: Validation checks before database operations (rarity validation, pack type validation, inventory limits)
- **User Feedback**: Rich embeds for card/pack displays, plain text for errors and confirmations
- **Future-Proofing**: Placeholder commands for pack trading (`!offerpack`, `!acceptpacktrade`) and other features (`!recycle`, `!buycredits`, `!launch`)

**Admin Commands**:
- `!addcard` - Add new cards to the collection
- `!setdroprate` - Configure guild-specific drop rates
- `!viewdroprates` - View current drop rate configuration (accessible to all, but admin-configurable)
- `!givecredits` - Award credits to users for testing/rewards
- `!resetpacktimer` - Reset free pack claim cooldown for testing

**Rationale**: Clear separation between implemented and planned features helps manage user expectations while providing a roadmap for development. Permission-based help system prevents confusion by only showing relevant commands.

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