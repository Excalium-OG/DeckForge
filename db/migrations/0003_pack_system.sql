CREATE TABLE IF NOT EXISTS user_packs (
    user_id BIGINT NOT NULL,
    pack_type TEXT NOT NULL,
    quantity INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, pack_type),
    CONSTRAINT positive_quantity CHECK (quantity >= 0)
);

CREATE TABLE IF NOT EXISTS pack_trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_id BIGINT NOT NULL,
    receiver_id BIGINT NOT NULL,
    pack_type TEXT NOT NULL,
    quantity INT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_status CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_pack_trades_receiver ON pack_trades(receiver_id, status);
CREATE INDEX IF NOT EXISTS idx_pack_trades_sender ON pack_trades(sender_id, status);
