ALTER TABLE outreach_draft
    ADD CONSTRAINT outreach_draft_id_user_key UNIQUE (id, user_id);

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE campaign (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    status TEXT NOT NULL CHECK (
        status IN (
            'draft', 'awaiting_approval', 'approved', 'running', 'paused',
            'completed', 'failed', 'cancelled'
        )
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, user_id)
);

CREATE INDEX campaign_user_status_updated_idx ON campaign (user_id, status, updated_at DESC);

CREATE TABLE campaign_recipient (
    id UUID PRIMARY KEY,
    campaign_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    outreach_draft_id UUID NOT NULL,
    draft_version INTEGER NOT NULL CHECK (draft_version > 0),
    recipient_email TEXT NOT NULL CHECK (length(recipient_email) BETWEEN 3 AND 320),
    status TEXT NOT NULL CHECK (
        status IN (
            'pending_approval', 'approved', 'queued', 'sending', 'sent',
            'failed', 'unknown', 'cancelled'
        )
    ),
    email_snapshot JSONB NOT NULL,
    provider_message_id TEXT,
    last_error TEXT CHECK (last_error IS NULL OR length(last_error) <= 1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (campaign_id, outreach_draft_id),
    FOREIGN KEY (campaign_id, user_id) REFERENCES campaign(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (outreach_draft_id, user_id)
        REFERENCES outreach_draft(id, user_id) ON DELETE CASCADE
);

CREATE INDEX campaign_recipient_user_campaign_idx
    ON campaign_recipient (user_id, campaign_id, created_at);

ALTER TABLE campaign ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_tenant_policy ON campaign
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE campaign_recipient ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_recipient FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_recipient_tenant_policy ON campaign_recipient
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

CREATE TABLE campaign_event (
    id UUID PRIMARY KEY,
    campaign_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor_user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (campaign_id, user_id) REFERENCES campaign(id, user_id) ON DELETE CASCADE
);

CREATE INDEX campaign_event_user_campaign_created_idx
    ON campaign_event (user_id, campaign_id, created_at);

ALTER TABLE campaign_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_event FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_event_tenant_policy ON campaign_event
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

CREATE TABLE email_provider_integration (
    user_id UUID PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider = 'gmail'),
    email_address TEXT NOT NULL CHECK (length(email_address) BETWEEN 3 AND 320),
    refresh_token_ciphertext BYTEA NOT NULL,
    scopes TEXT[] NOT NULL,
    sync_after TIMESTAMPTZ,
    sync_page_token TEXT,
    sync_base_after TIMESTAMPTZ,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE email_provider_integration ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_provider_integration FORCE ROW LEVEL SECURITY;
CREATE POLICY email_provider_integration_tenant_policy ON email_provider_integration
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

CREATE TABLE email_oauth_state (
    state_hash TEXT PRIMARY KEY CHECK (length(state_hash) = 64),
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);

CREATE INDEX email_oauth_state_expiry_idx ON email_oauth_state (expires_at);

CREATE TABLE email_message (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    provider_message_id TEXT NOT NULL,
    provider_thread_id TEXT NOT NULL,
    sender TEXT,
    recipients TEXT[] NOT NULL DEFAULT '{}',
    subject TEXT,
    received_at TIMESTAMPTZ,
    snippet TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    labels TEXT[] NOT NULL DEFAULT '{}',
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider_message_id)
);

CREATE INDEX email_message_user_received_idx
    ON email_message (user_id, received_at DESC NULLS LAST);

ALTER TABLE email_message ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_message FORCE ROW LEVEL SECURITY;
CREATE POLICY email_message_tenant_policy ON email_message
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
