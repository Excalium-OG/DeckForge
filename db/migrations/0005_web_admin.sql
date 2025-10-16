-- Web Admin Portal Migration
-- Adds deck management system for web-based admin interface

-- Decks table: Collections of cards that can be assigned to servers
CREATE TABLE IF NOT EXISTS decks (
    deck_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_by BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Server-Deck assignments: Maps Discord servers to specific decks
CREATE TABLE IF NOT EXISTS server_decks (
    guild_id BIGINT PRIMARY KEY,
    deck_id INT REFERENCES decks(deck_id) ON DELETE SET NULL
);

-- Rarity ranges: Deck-specific drop rate configuration
CREATE TABLE IF NOT EXISTS rarity_ranges (
    deck_id INT REFERENCES decks(deck_id) ON DELETE CASCADE,
    rarity TEXT NOT NULL,
    drop_rate FLOAT NOT NULL CHECK (drop_rate >= 0 AND drop_rate <= 100),
    PRIMARY KEY (deck_id, rarity)
);

-- Update cards table to support deck assignments
ALTER TABLE cards ADD COLUMN IF NOT EXISTS deck_id INT REFERENCES decks(deck_id) ON DELETE CASCADE;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_cards_deck ON cards(deck_id);
CREATE INDEX IF NOT EXISTS idx_server_decks_deck ON server_decks(deck_id);
CREATE INDEX IF NOT EXISTS idx_rarity_ranges_deck ON rarity_ranges(deck_id);
