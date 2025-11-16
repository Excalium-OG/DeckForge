-- Migration 0010: User Card Field Overrides
-- Stores instance-specific boosted field values for merged cards

CREATE TABLE IF NOT EXISTS user_card_field_overrides (
    instance_id UUID NOT NULL REFERENCES user_cards(instance_id) ON DELETE CASCADE,
    template_id INT NOT NULL REFERENCES card_templates(template_id) ON DELETE CASCADE,
    base_value VARCHAR(500),
    effective_numeric_value NUMERIC(10, 2),
    overridden_value VARCHAR(500),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (instance_id, template_id)
);

CREATE INDEX IF NOT EXISTS idx_user_card_field_overrides_instance ON user_card_field_overrides(instance_id);

COMMENT ON TABLE user_card_field_overrides IS 'Stores instance-specific field value overrides for merged cards';
COMMENT ON COLUMN user_card_field_overrides.base_value IS 'Snapshot of the base field value when boost was applied';
COMMENT ON COLUMN user_card_field_overrides.effective_numeric_value IS 'Calculated numeric value after applying boost (for numeric fields)';
COMMENT ON COLUMN user_card_field_overrides.overridden_value IS 'The final display value (numeric or text)';
COMMENT ON COLUMN user_card_field_overrides.metadata IS 'Additional calculation details (cumulative_boost_pct, calculation_timestamp, etc)';
