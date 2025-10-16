-- Migration 0007: Card Templates and Server Settings
-- Add support for custom card field templates and server-specific settings

-- Add free pack cooldown to decks table
ALTER TABLE decks ADD COLUMN IF NOT EXISTS free_pack_cooldown_hours INTEGER DEFAULT 8 CHECK (free_pack_cooldown_hours BETWEEN 1 AND 168);

-- Card template definitions for each deck
CREATE TABLE IF NOT EXISTS card_templates (
    template_id SERIAL PRIMARY KEY,
    deck_id INTEGER NOT NULL REFERENCES decks(deck_id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    field_type VARCHAR(20) NOT NULL CHECK (field_type IN ('text', 'number', 'dropdown')),
    dropdown_options TEXT,
    field_order INTEGER DEFAULT 0,
    is_required BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(deck_id, field_name)
);

-- Card template field values (stores actual card data)
CREATE TABLE IF NOT EXISTS card_template_fields (
    field_id SERIAL PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
    template_id INTEGER NOT NULL REFERENCES card_templates(template_id) ON DELETE CASCADE,
    field_value TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(card_id, template_id)
);

-- Server-specific settings
CREATE TABLE IF NOT EXISTS server_settings (
    guild_id BIGINT PRIMARY KEY,
    free_pack_cooldown_override INTEGER CHECK (free_pack_cooldown_override BETWEEN 1 AND 168),
    settings_data JSONB DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_card_templates_deck ON card_templates(deck_id);
CREATE INDEX IF NOT EXISTS idx_card_template_fields_card ON card_template_fields(card_id);
CREATE INDEX IF NOT EXISTS idx_card_template_fields_template ON card_template_fields(template_id);
