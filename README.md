# DeckForge - Discord Trading Card Bot

A Discord bot for a collectible rocket-themed trading card game with drop mechanics, card management, and admin tools.

## Features (Phase 1)

### Core Commands
- `!drop` - Claim 2 random cards every 8 hours (uses weighted drop rates)
- `!mycards` - View your card collection sorted by rarity
- `!cardinfo [name or ID]` - View detailed card information
- `!balance` - Check your credit balance
- `!viewdroprates` - View current drop rate configuration for the server

### Future Features (Placeholders)
- `!recycle [instance_id]` - Recycle cards for credits (Phase 2)
- `!buycredits [amount]` - Buy credits (Phase 2 - Stripe integration)
- `!launch [instance_id]` - Launch rocket cards (Phase 2 - gameplay)

## Setup

### Prerequisites
- Python 3.11+
- PostgreSQL database
- Discord bot application

### Environment Variables
- `DECKFORGE_BOT_TOKEN` - Your Discord bot token (required)
- `DATABASE_URL` - PostgreSQL connection string (auto-configured)
- `ADMIN_IDS` - Comma-separated Discord user IDs for admins (optional)

### Running the Bot
```bash
python bot.py
```

## Rarity System

Cards are sorted by the following rarity hierarchy:
1. Common
2. Uncommon
3. Exceptional
4. Rare
5. Epic
6. Legendary
7. Mythic

### Default Drop Rates

| Rarity      | Drop Rate |
|-------------|-----------|
| Common      | 40%       |
| Uncommon    | 25%       |
| Exceptional | 15%       |
| Rare        | 10%       |
| Epic        | 6%        |
| Legendary   | 3%        |
| Mythic      | 1%        |

Admins can customize these rates per server using `!setdroprate`. All rates must total 100%.

## Database Schema

- **players** - User profiles, credits, and drop cooldowns
- **cards** - Master card definitions
- **user_cards** - Player-owned card instances with UUIDs
- **drop_rates** - Configurable drop rates per guild (Phase 1.5)
- **pending_trades** - Future trading system (Phase 2)

## Project Structure
```
.
├── bot.py                  # Main bot entry point
├── cogs/
│   ├── cards.py           # Core card commands
│   └── future.py          # Placeholder commands
├── utils/
│   ├── card_helpers.py    # Card utility functions
│   └── drop_helpers.py    # Drop rate utilities
├── db/
│   └── migrations/
│       ├── 0001_cardbot.sql      # Initial schema
│       └── 0002_drop_rates.sql   # Drop rates config
└── tests/
```

## Coming in Phase 2
- Trading system with confirmation workflow
- Card recycling with rarity-based credit rewards
- Stripe microtransactions integration
- Card battle/launch gameplay mechanics
- Leaderboards and statistics
