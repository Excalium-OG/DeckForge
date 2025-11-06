-- Migration 0008: Card Merge System
-- Adds mergeable attributes, merge levels, and perk progression tracking

-- Add merge-related fields to cards table (if they don't exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='cards' AND column_name='mergeable') THEN
        ALTER TABLE cards ADD COLUMN mergeable BOOLEAN DEFAULT FALSE;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='cards' AND column_name='max_merge_level') THEN
        ALTER TABLE cards ADD COLUMN max_merge_level INTEGER DEFAULT 10;
    END IF;
END $$;

-- Add merge tracking fields to user_cards table (if they don't exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='user_cards' AND column_name='merge_level') THEN
        ALTER TABLE user_cards ADD COLUMN merge_level INTEGER DEFAULT 0;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='user_cards' AND column_name='locked_perk') THEN
        ALTER TABLE user_cards ADD COLUMN locked_perk VARCHAR(100);
    END IF;
END $$;

-- Create card_perks table to track perk progression per merge level
CREATE TABLE IF NOT EXISTS card_perks (
    perk_id SERIAL PRIMARY KEY,
    instance_id UUID NOT NULL REFERENCES user_cards(instance_id) ON DELETE CASCADE,
    level_applied INTEGER NOT NULL,
    characteristic_name VARCHAR(100) NOT NULL,
    perk_value NUMERIC(10, 2) NOT NULL,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instance_id, level_applied)
);

-- Add index for faster perk lookups (if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_card_perks_instance') THEN
        CREATE INDEX idx_card_perks_instance ON card_perks(instance_id);
    END IF;
END $$;

-- Add merge_perks field to card_templates table (if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='card_templates' AND column_name='is_merge_perk') THEN
        ALTER TABLE card_templates ADD COLUMN is_merge_perk BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- Create table to track merge-eligible perks per deck
CREATE TABLE IF NOT EXISTS deck_merge_perks (
    deck_id INTEGER NOT NULL REFERENCES decks(deck_id) ON DELETE CASCADE,
    perk_name VARCHAR(100) NOT NULL,
    base_boost NUMERIC(10, 2) DEFAULT 10.0,
    diminishing_factor NUMERIC(4, 3) DEFAULT 0.85,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (deck_id, perk_name)
);

-- Add index for deck merge perks lookups (if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_deck_merge_perks_deck') THEN
        CREATE INDEX idx_deck_merge_perks_deck ON deck_merge_perks(deck_id);
    END IF;
END $$;

COMMENT ON COLUMN cards.mergeable IS 'Whether this card can participate in merge operations';
COMMENT ON COLUMN cards.max_merge_level IS 'Maximum merge level achievable for this card';
COMMENT ON COLUMN user_cards.merge_level IS 'Current merge level of this card instance';
COMMENT ON COLUMN user_cards.locked_perk IS 'The perk chosen on first merge, locked for all future merges';
COMMENT ON TABLE card_perks IS 'Tracks perk progression history for merged cards';
COMMENT ON TABLE deck_merge_perks IS 'Defines available merge perks and their scaling parameters per deck';
