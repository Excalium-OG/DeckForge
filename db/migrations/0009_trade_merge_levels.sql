-- Migration 0009: Add merge level tracking to trades
-- Allows trading cards with different merge levels separately

-- Add merge_level column to trade_items (if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='trade_items' AND column_name='merge_level') THEN
        -- First, add the column with default value
        ALTER TABLE trade_items ADD COLUMN merge_level INTEGER DEFAULT 0;
        
        -- Then drop the old primary key
        ALTER TABLE trade_items DROP CONSTRAINT trade_items_pkey;
        
        -- Add new primary key that includes merge_level
        ALTER TABLE trade_items ADD PRIMARY KEY (trade_id, user_id, card_id, merge_level);
    END IF;
END $$;

COMMENT ON COLUMN trade_items.merge_level IS 'Merge level of the cards being traded (allows differentiation between same card at different levels)';
