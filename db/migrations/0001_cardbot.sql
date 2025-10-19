-- DeckForge Card Bot Migration v0001
-- Phase 1: Core trading card system tables

-- Player profile and cooldown tracking
CREATE TABLE IF NOT EXISTS players (
  user_id BIGINT PRIMARY KEY,
  credits INT DEFAULT 0,
  last_drop_ts TIMESTAMP WITH TIME ZONE
);

-- Master card definitions
CREATE TABLE IF NOT EXISTS cards (
  card_id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  rarity TEXT NOT NULL,
  description TEXT,
  image_url TEXT,
  stats JSONB DEFAULT '{}'::jsonb,
  created_by BIGINT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Player-owned card instances
CREATE TABLE IF NOT EXISTS user_cards (
  instance_id UUID PRIMARY KEY,
  user_id BIGINT NOT NULL,
  card_id INT REFERENCES cards(card_id),
  acquired_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  source TEXT
);

-- Future: Pending trades table
CREATE TABLE IF NOT EXISTS pending_trades (
  trade_id SERIAL PRIMARY KEY,
  sender_id BIGINT NOT NULL,
  receiver_id BIGINT NOT NULL,
  offered_instance_id UUID REFERENCES user_cards(instance_id),
  requested_instance_id UUID REFERENCES user_cards(instance_id),
  status TEXT DEFAULT 'pending',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_cards_user_id ON user_cards(user_id);
CREATE INDEX IF NOT EXISTS idx_user_cards_card_id ON user_cards(card_id);
CREATE INDEX IF NOT EXISTS idx_pending_trades_sender ON pending_trades(sender_id);
CREATE INDEX IF NOT EXISTS idx_pending_trades_receiver ON pending_trades(receiver_id);
