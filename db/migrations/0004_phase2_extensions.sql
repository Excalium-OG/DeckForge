-- Phase 2 Extensions Migration
-- Adds trading system tables and extended card metadata fields

-- Trading System Tables
CREATE TABLE IF NOT EXISTS trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    initiator_id BIGINT NOT NULL,
    responder_id BIGINT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'accepted', 'completed', 'cancelled', 'expired')),
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finalized_at TIMESTAMP WITH TIME ZONE,
    initiator_accepted BOOLEAN DEFAULT FALSE,
    responder_accepted BOOLEAN DEFAULT FALSE,
    initiator_finalized BOOLEAN DEFAULT FALSE,
    responder_finalized BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS trade_items (
    trade_id UUID REFERENCES trades(trade_id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    card_id INT NOT NULL REFERENCES cards(card_id),
    quantity INT NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (trade_id, user_id, card_id)
);

-- Extended Card Metadata Fields
ALTER TABLE cards ADD COLUMN IF NOT EXISTS height TEXT;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS diameter TEXT;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS thrust TEXT;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS payload_leo TEXT;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS reusability TEXT CHECK (reusability IN ('Expendable', 'Partially Reusable', 'Fully Reusable'));

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trades_initiator ON trades(initiator_id);
CREATE INDEX IF NOT EXISTS idx_trades_responder ON trades(responder_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trade_items_card ON trade_items(card_id);

-- Add recycled_at timestamp to user_cards for recycling tracking
ALTER TABLE user_cards ADD COLUMN IF NOT EXISTS recycled_at TIMESTAMP WITH TIME ZONE;
