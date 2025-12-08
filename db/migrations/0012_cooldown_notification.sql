-- DeckForge Mission System Enhancement v0012
-- Add cooldown notification tracking column

-- Add cooldown_notified column to user_mission_cooldowns if not exists
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_mission_cooldowns' 
        AND column_name = 'cooldown_notified'
    ) THEN
        ALTER TABLE user_mission_cooldowns 
        ADD COLUMN cooldown_notified BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- Backfill existing rows to have cooldown_notified = TRUE 
-- (so we don't spam notifications to existing users who already had cooldowns expire)
UPDATE user_mission_cooldowns 
SET cooldown_notified = TRUE 
WHERE cooldown_notified IS NULL;
