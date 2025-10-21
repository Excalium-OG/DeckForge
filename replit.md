# DeckForge - Discord Trading Card Bot

## Overview
DeckForge is a Discord bot implementing a collectible rocket-themed trading card game. Its primary purpose is to allow users to collect cards through a time-gated drop system, manage their collections, and interact with card information. The project aims for a phased rollout, with current development focusing on core collection mechanics, admin tools, an enhanced inventory, card recycling, player-to-player trading, and a web-based deck management portal. Future ambitions include full gameplay, advanced trading features, and monetization.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Discord Bot**: Built using `discord.py` v2.6.4 with a cog-based architecture for modularity. Features include slash commands (`/`) as the primary interface with legacy prefix commands (`!`) for backward compatibility. Uses hybrid commands, a custom bot class (`DeckForgeBot`), and dedicated cogs for cards, packs, trading, and help.
- **Web Admin Portal**: Developed with FastAPI, Uvicorn, and Jinja2 for a web-based interface.

### Authentication & Authorization
- **Discord Bot**: Role-based access control via Discord user IDs stored in `ADMIN_IDS`. Bot owner has automatic admin privileges.
- **Web Admin Portal**: Discord OAuth2 for authentication. Authorization is two-tier: global admins have full access, and server managers can manage decks for servers where they have `MANAGE_SERVER` permission.

### Data Layer
- **Database**: PostgreSQL is used for all persistent storage, managed with `asyncpg` for asynchronous operations and connection pooling.
- **Schema**: Key tables include `players`, `cards`, `user_cards`, `drop_rates`, `user_packs`, `trades`, `trade_items`, `decks`, `server_decks`, `rarity_ranges`, `card_templates`, `card_template_fields`, and `server_settings`. `user_cards` uses UUIDs for unique instance tracking.
- **Custom Card Templates**: The `card_templates` table stores custom field definitions per deck (field name, type, required flag, display order), while `card_template_fields` stores actual field values for each card. Supports text, number, and dropdown field types.
- **Server Settings**: The `server_settings` table stores per-server configurations including active deck assignments and customizations.

### Core Game Mechanics
- **Pack System**: Three pack types (Normal, Booster, Booster+). Users can claim a free Normal Pack every 8 hours or purchase packs with credits. Packs have a 30-item inventory limit, and Booster Packs apply rarity multipliers.
- **Card System**: Seven-tier rarity system (Common to Mythic) with configurable weighted drop rates per guild. Cards are instance-based (UUID) and sorted by rarity then alphabetically.
- **Inventory Management**: `/mycards` command groups identical cards, supports pagination with reaction-based navigation, and displays total/unique card counts.
- **Card Recycling**: `/recycle` command allows users to convert duplicate cards into credits based on rarity. Cards are soft-deleted via a `recycled_at` timestamp.
- **Player-to-Player Trading**: A multi-step `/requesttrade` system with `/tradeadd`/`/traderemove`, `/accepttrade`, and `/finalize` commands. Trades have a 5-minute timeout and include safety features like inventory validation and atomic transfers.

### Web Admin Portal Features
- **Dashboard**: Displays user info, managed Discord servers, assigned decks, and user-created decks.
- **Deck Management**: Allows creation, editing (adding/deleting cards with detailed specifications), and viewing of cards within a deck.
- **Rarity Rate Editor**: Configurable drop rates per rarity tier for decks, with real-time validation to ensure rates sum to 100%.
- **Image Upload**: Direct file upload from client device using Replit object storage with presigned URLs for secure, scalable image hosting.
- **Custom Card Templates**: Define custom field schemas for each deck with field name, type (text/number/dropdown), required flag, and display order. Card creation forms dynamically adapt to the deck's template.
- **Free Pack Cooldown Editor**: Configurable 1-168 hour cooldowns per deck for free pack claims, allowing deck creators to customize pack distribution rates.

### Image & Asset Management
- **Web Portal**: Card images uploaded via web admin portal are stored in Replit object storage. The system uses:
  - Direct client-to-storage uploads via presigned URLs (no server intermediary)
  - Google Cloud Storage with Replit sidecar authentication
  - Image paths stored in database format: `/images/card-images/{uuid}`
  - Automatic content-type detection and caching for optimal performance
- **Discord Bot**: Admin commands support image uploads via Discord attachments, stored as URLs in the database.

### Command Design Patterns
- **Slash Commands**: 10 slash commands implemented using hybrid commands (work as both `/` and `!`):
  - `/drop`, `/mycards`, `/recycle`, `/claimfreepack`, `/buypack`, `/mypacks` - Hybrid commands
  - `/cardinfo` (with autocomplete), `/help`, `/balance`, `/buycredits` - Pure slash commands
- **Hybrid Command Architecture**: Commands use `ctx.defer()` for slash invocations to prevent 3-second timeout errors
- **Help System**: Custom help command filters admin-only commands for non-admin users
- **Error Handling**: Extensive validation checks are performed before database operations
- **User Feedback**: Utilizes rich embeds for card/pack displays and plain text for confirmations

## External Dependencies

### Required Services
- **Discord API**: Integrated via `discord.py`, requiring `DECKFORGE_BOT_TOKEN`, `MESSAGE CONTENT INTENT`, and optionally `SERVER MEMBERS INTENT`.
- **PostgreSQL Database**: Data persistence layer, accessed via `DATABASE_URL` environment variable.

### Python Libraries
- **Discord Bot**: `discord.py`, `asyncpg`, `python-dotenv`.
- **Web Admin Portal**: `FastAPI`, `Uvicorn`, `Authlib` (for Discord OAuth2), `Jinja2`, `httpx`, `itsdangerous`.

### Environment Configuration
- `DECKFORGE_BOT_TOKEN`, `DATABASE_URL`, `ADMIN_IDS` (optional) for the Discord bot.
- `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `SESSION_SECRET`, `DISCORD_REDIRECT_URI` for the Web Admin Portal.
- `PRIVATE_OBJECT_DIR` for Replit object storage (format: `/bucket-name/path`, required for image uploads).

### Future Integrations (Planned)
- **Stripe API**: For credit purchases.
- **Image Storage Service**: For dedicated card image hosting.