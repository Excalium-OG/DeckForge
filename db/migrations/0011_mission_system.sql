-- DeckForge Mission System Migration v0011
-- Card Activity Mission System with templates, active missions, and user mission tracking

-- Mission status enum
DO $$ BEGIN
    CREATE TYPE mission_status AS ENUM ('pending', 'active', 'completed', 'rejected', 'expired', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Mission templates defined by deck creators
CREATE TABLE IF NOT EXISTS mission_templates (
    mission_template_id SERIAL PRIMARY KEY,
    deck_id INTEGER NOT NULL REFERENCES decks(deck_id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    activity_type VARCHAR(50) NOT NULL DEFAULT 'mission',
    requirement_field VARCHAR(100) NOT NULL,
    min_value_base FLOAT NOT NULL,
    reward_base INTEGER NOT NULL,
    duration_base_hours INTEGER NOT NULL DEFAULT 48,
    variance_pct FLOAT NOT NULL DEFAULT 5.0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Rarity scaling configuration for mission templates
CREATE TABLE IF NOT EXISTS mission_rarity_scaling (
    scaling_id SERIAL PRIMARY KEY,
    mission_template_id INTEGER NOT NULL REFERENCES mission_templates(mission_template_id) ON DELETE CASCADE,
    rarity VARCHAR(20) NOT NULL,
    requirement_multiplier FLOAT NOT NULL DEFAULT 1.0,
    reward_multiplier FLOAT NOT NULL DEFAULT 1.0,
    duration_multiplier FLOAT NOT NULL DEFAULT 1.0,
    success_rate FLOAT NOT NULL DEFAULT 50.0,
    UNIQUE(mission_template_id, rarity)
);

-- Active missions spawned in servers
CREATE TABLE IF NOT EXISTS active_missions (
    active_mission_id SERIAL PRIMARY KEY,
    mission_template_id INTEGER NOT NULL REFERENCES mission_templates(mission_template_id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL,
    deck_id INTEGER NOT NULL REFERENCES decks(deck_id) ON DELETE CASCADE,
    channel_id BIGINT,
    message_id BIGINT,
    spawned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reaction_expires_at TIMESTAMP WITH TIME ZONE,
    mission_expires_at TIMESTAMP WITH TIME ZONE,
    status mission_status NOT NULL DEFAULT 'pending',
    rarity_rolled VARCHAR(20) NOT NULL,
    requirement_rolled FLOAT NOT NULL,
    reward_rolled INTEGER NOT NULL,
    duration_rolled_hours INTEGER NOT NULL,
    accepted_by BIGINT,
    accepted_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    card_instance_id UUID,
    success_roll FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User mission history and cooldowns
CREATE TABLE IF NOT EXISTS user_missions (
    user_mission_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    active_mission_id INTEGER NOT NULL REFERENCES active_missions(active_mission_id) ON DELETE CASCADE,
    status mission_status NOT NULL DEFAULT 'pending',
    acceptance_cost INTEGER NOT NULL DEFAULT 0,
    credits_earned INTEGER DEFAULT 0,
    accepted_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    card_instance_id UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Server mission settings (extend with mission channel)
CREATE TABLE IF NOT EXISTS server_mission_settings (
    guild_id BIGINT PRIMARY KEY,
    deck_id INTEGER REFERENCES decks(deck_id) ON DELETE SET NULL,
    mission_channel_id BIGINT,
    missions_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    last_mission_spawn TIMESTAMP WITH TIME ZONE,
    activity_message_count INTEGER DEFAULT 0,
    activity_unique_users INTEGER DEFAULT 0,
    activity_window_start TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User mission cooldowns
CREATE TABLE IF NOT EXISTS user_mission_cooldowns (
    user_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    last_accept_time TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_mission_templates_deck ON mission_templates(deck_id);
CREATE INDEX IF NOT EXISTS idx_mission_templates_active ON mission_templates(deck_id, is_active);
CREATE INDEX IF NOT EXISTS idx_active_missions_guild ON active_missions(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_active_missions_status ON active_missions(status, reaction_expires_at);
CREATE INDEX IF NOT EXISTS idx_user_missions_user ON user_missions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_missions_active ON user_missions(active_mission_id);

-- Insert default rarity scaling for new mission templates
CREATE OR REPLACE FUNCTION insert_default_rarity_scaling()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO mission_rarity_scaling (mission_template_id, rarity, requirement_multiplier, reward_multiplier, duration_multiplier, success_rate)
    VALUES 
        (NEW.mission_template_id, 'Common', 0.3, 0.2, 0.5, 40.0),
        (NEW.mission_template_id, 'Uncommon', 0.4, 0.3, 0.6, 50.0),
        (NEW.mission_template_id, 'Exceptional', 0.5, 0.4, 0.7, 60.0),
        (NEW.mission_template_id, 'Rare', 0.6, 0.5, 0.8, 65.0),
        (NEW.mission_template_id, 'Epic', 0.75, 0.7, 0.9, 75.0),
        (NEW.mission_template_id, 'Legendary', 0.9, 0.85, 0.95, 90.0),
        (NEW.mission_template_id, 'Mythic', 1.0, 1.0, 1.0, 99.0);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_insert_rarity_scaling ON mission_templates;
CREATE TRIGGER trigger_insert_rarity_scaling
    AFTER INSERT ON mission_templates
    FOR EACH ROW
    EXECUTE FUNCTION insert_default_rarity_scaling();
