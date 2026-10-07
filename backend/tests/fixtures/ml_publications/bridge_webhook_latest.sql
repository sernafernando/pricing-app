-- DDL of the bridge table `webhook_latest`, copied from the bridge repo migration
-- ml-webhook/migrations/20260410_01_add_webhook_latest.sql (read-only reference). The runtime-role GRANT
-- is left out: the tests create the table in a throwaway schema of the test database.
CREATE TABLE IF NOT EXISTS webhook_latest (
    topic TEXT NOT NULL,
    resource TEXT NOT NULL,
    webhook_id TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL,
    PRIMARY KEY (topic, resource)
);

CREATE INDEX IF NOT EXISTS idx_webhook_latest_topic_received_resource
    ON webhook_latest (topic, received_at DESC, resource DESC);
