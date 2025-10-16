# DeckForge - Discord Trading Card Bot

## Overview
DeckForge is a Discord bot implementing a collectible rocket-themed trading card game. Its primary purpose is to allow users to collect cards through a time-gated drop system, manage their collections, and interact with card information. The project aims for a phased rollout, with current development focusing on core collection mechanics, admin tools, an enhanced inventory, card recycling, player-to-player trading, and a web-based deck management portal. Future ambitions include full gameplay, advanced trading features, and monetization.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Discord Bot**: Built using `discord.py` with a cog-based architecture for modularity. Features include prefix-based commands (`!`), a custom bot class (`DeckForgeBot`), and dedicated cogs for cards, packs, trading, and help.
- **Web Admin Portal**: Developed with FastAPI, Uvicorn, and Jinja2 for a web-based interface.

### Authentication & Authorization
- **Discord Bot**: Role-based access control via Discord user IDs stored in `ADMIN_IDS`. Bot owner has automatic admin privileges.
- **Web Admin Portal**: Discord OAuth2 for authentication. Authorization is two-tier: global admins have full access, and server managers can manage decks for servers where they have `MANAGE_SERVER` permission.

### Data Layer
- **Database**: PostgreSQL is used for all persistent storage, managed with `asyncpg` for asynchronous operations and connection pooling.
- **Schema**: Key tables include `players`, `cards`, `user_cards`, `drop_rates`, `user_packs`, `trades`, `trade_items`, `decks`, `server_decks`, and `rarity_ranges`. `user_cards` uses UUIDs for unique instance tracking.

### Core Game Mechanics
- **Pack System**: Three pack types (Normal, Booster, Booster+). Users can claim a free Normal Pack every 8 hours or purchase packs with credits. Packs have a 30-item inventory limit, and Booster Packs apply rarity multipliers.
- **Card System**: Seven-tier rarity system (Common to Mythic) with configurable weighted drop rates per guild. Cards are instance-based (UUID) and sorted by rarity then alphabetically.
- **Inventory Management**: `!mycards` command groups identical cards, supports pagination with reaction-based navigation, and displays total/unique card counts.
- **Card Recycling**: `!recycle` command allows users to convert duplicate cards into credits based on rarity. Cards are soft-deleted via a `recycled_at` timestamp.
- **Player-to-Player Trading**: A multi-step `!requesttrade` system with `!tradeadd`/`!traderemove`, `!accepttrade`, and `!finalize` commands. Trades have a 5-minute timeout and include safety features like inventory validation and atomic transfers.

### Web Admin Portal Features
- **Dashboard**: Displays user info, managed Discord servers, assigned decks, and user-created decks.
- **Deck Management**: Allows creation, editing (adding/deleting cards with detailed specifications), and viewing of cards within a deck.
- **Rarity Rate Editor**: Configurable drop rates per rarity tier for decks, with real-time validation to ensure rates sum to 100%.

### Image & Asset Management
- Card images are stored as URLs in the database. Admin commands support image uploads via Discord attachments.

### Command Design Patterns
- **Help System**: Custom help command filters admin-only commands for non-admin users.
- **Error Handling**: Extensive validation checks are performed before database operations.
- **User Feedback**: Utilizes rich embeds for card/pack displays and plain text for confirmations.

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

### Future Integrations (Planned)
- **Stripe API**: For credit purchases.
- **Image Storage Service**: For dedicated card image hosting.