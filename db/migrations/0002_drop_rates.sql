-- DeckForge Drop Rates Migration v0002
-- Configurable rarity drop rates per guild

CREATE TABLE IF NOT EXISTS drop_rates (
  guild_id BIGINT,
  rarity TEXT,
  percentage FLOAT,
  PRIMARY KEY (guild_id, rarity)
);

-- Index for faster guild lookups
CREATE INDEX IF NOT EXISTS idx_drop_rates_guild ON drop_rates(guild_id);
