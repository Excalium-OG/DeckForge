# DeckForge - Discord Trading Card Bot

## Overview

DeckForge is a Discord bot that implements a collectible rocket-themed trading card game. The bot enables users to collect cards through a time-gated drop system, view their collections, and interact with card information. The system is designed with a phased rollout approach, with Phase 1 focusing on core card collection mechanics and admin tools, while future phases will introduce gameplay mechanics, trading, and monetization features.

**Status**: Phase 2 Extensions ✅ - Enhanced inventory UX, card recycling system, and player-to-player trading

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Discord Bot Framework**: Built using discord.py with command extension (discord.ext.commands)
- **Command System**: Prefix-based commands using "!" as the command prefix
- **Bot Architecture**: Custom bot class (DeckForgeBot) extends commands.Bot to integrate database connection pooling
- **Code Organization**: Cog-based architecture to separate concerns:
  - `cogs/cards.py` - Card management commands (!drop, !mycards, !cardinfo, !addcard, !recycle)
  - `cogs/packs.py` - Pack inventory and claiming commands (!claimfreepack, !mypacks, !buypack)
  - `cogs/trading.py` - Player-to-player trading system (!requesttrade, !accepttrade, !tradeadd, !traderemove, !finalize)
  - `cogs/custom_help.py` - Permission-aware help command
  - `cogs/future.py` - Placeholder commands for future features (!buycredits, !launch)
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
- **Schema Design**: Eight core tables:
  1. `players` - User profiles, credits, and pack claim cooldown timestamps
  2. `cards` - Master card definitions with metadata, images, and extended rocket specifications
  3. `user_cards` - Individual card instances owned by players (uses UUID for unique identification, includes recycled_at timestamp)
  4. `drop_rates` - Guild-specific rarity drop rate configuration (guild_id, rarity, percentage)
  5. `user_packs` - Pack inventory per user (user_id, pack_type, quantity) with 30 total pack limit
  6. `trades` - Active and completed card trades between players (UUID-based trade sessions with 5-minute timeout)
  7. `trade_items` - Items offered in trades (card_id, quantity per user per trade)
  8. Extended card fields: height, diameter, thrust, payload_leo, reusability

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

#### Inventory Management (Phase 2 Extensions)
- **Card Grouping**: !mycards groups identical cards by card_id with quantity display (x7) Falcon 9 (ID: 1)
- **Pagination**: 8 cards per page with reaction-based navigation (⬅️ ➡️)
- **Display Format**: Shows total cards owned and unique card count
- **Navigation**: 60-second timeout for reactions, auto-cleanup after timeout
- **No Image Previews**: Inventory displays as simple list for better performance

**Rationale**: Grouping reduces clutter for users with many duplicates. Pagination handles large collections gracefully. Reaction-based navigation provides intuitive UX without requiring text commands.

#### Card Recycling System (Phase 2 Extensions)
- **Command**: !recycle [card_id] [amount] - Recycle duplicate cards for credits
- **Credit Values by Rarity**:
  - Common: 10 credits
  - Uncommon: 25 credits
  - Exceptional: 50 credits
  - Rare: 100 credits
  - Epic: 250 credits
  - Legendary: 500 credits
  - Mythic: 1000 credits
- **Soft Delete**: Cards marked with `recycled_at` timestamp (preserves history)
- **Validation**: Checks user owns sufficient quantity before recycling
- **Limit**: Maximum 100 cards per recycle operation
- **Transaction Safety**: Credits awarded and cards marked atomically

**Rationale**: Recycling gives players a way to convert duplicates into progression currency. Soft delete preserves data for potential future features (rollback, statistics). Tiered pricing encourages strategic decisions about which cards to recycle.

#### Player-to-Player Trading (Phase 2 Extensions)
- **Trade Flow**: Multi-step confirmation process ensures both parties agree
  1. !requesttrade @user - Initiates trade session
  2. !accepttrade - Responder accepts invitation (activates trade)
  3. !tradeadd [card_id] [amount] - Add cards to your offer
  4. !traderemove [card_id] [amount] - Remove cards from your offer
  5. !accepttrade (both users) - Confirm final trade terms
  6. !finalize (both users) - Execute the trade
- **Trade Timeout**: 5-minute expiration prevents stale sessions
- **Trade Pool Visualization**: Dynamic embed shows both offers with rarity info
- **State Management**: Trade status tracking (pending → active → accepted → completed)
- **Safety Features**:
  - Can't trade with yourself or bots
  - Only one active trade per user at a time
  - Inventory validation before trade execution
  - Atomic transfers in transaction
  - Acceptances reset when trade pool changes
- **Additional Commands**:
  - !canceltrade - Cancel active trade

**Rationale**: Multi-step process prevents accidental trades and scams. Visual trade pool helps players verify offers. 5-minute timeout prevents abandoned trades from blocking users. Atomic transactions ensure trade integrity. State tracking provides clear UX about trade progress.

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
**Player Commands**:
- `!claimfreepack` - Claim free Normal Pack (8-hour cooldown)
- `!drop [amount] [pack_type]` - Open packs to receive cards
- `!mypacks` - View pack inventory
- `!mycards` - View card collection with pagination
- `!cardinfo [name/ID]` - View detailed card information
- `!buypack [amount] [pack_type]` - Purchase packs with credits
- `!recycle [card_id] [amount]` - Recycle cards for credits
- `!requesttrade @user` - Initiate trade with another player
- `!accepttrade` - Accept trade request or confirm trade terms
- `!tradeadd [card_id] [amount]` - Add cards to trade offer
- `!traderemove [card_id] [amount]` - Remove cards from trade offer
- `!finalize` - Execute trade (both players must confirm)
- `!canceltrade` - Cancel active trade
- `!balance` - Check credit balance
- `!viewdroprates` - View server drop rate configuration

**Admin Commands**:
- `!addcard [rarity] [name] [description]` - Add new cards with image
- `!setdroprate [rarity] [percentage]` - Configure guild-specific drop rates
- `!givecredits @user [amount]` - Award credits to users
- `!resetpacktimer [@user]` - Reset free pack claim cooldown
- `!updateimage [card_id]` - Update card image (with attachment)

**Future Features**:
- `!buycredits [amount]` - Purchase credits (Stripe integration planned)
- `!launch [instance_id]` - Gameplay mechanics (Phase 3)

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