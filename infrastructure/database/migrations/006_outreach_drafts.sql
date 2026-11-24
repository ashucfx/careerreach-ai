CREATE TABLE outreach_draft (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    recruiter_id UUID NOT NULL,
    job_id UUID NOT NULL,
    profile_id UUID NOT NULL,
    profile_version INTEGER NOT NULL CHECK (profile_version > 0),
    version INTEGER NOT NULL CHECK (version > 0),
    tone TEXT NOT NULL CHECK (tone IN ('warm', 'direct', 'formal')),
    strategy JSONB NOT NULL,
    email JSONB NOT NULL,
    evidence_snapshot JSONB NOT NULL,
    model TEXT NOT NULL CHECK (length(model) BETWEEN 1 AND 200),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recruiter_id, job_id, profile_version, version),
    FOREIGN KEY (recruiter_id, user_id)
        REFERENCES recruiter_contact(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (job_id, user_id) REFERENCES job_listing(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (profile_id, user_id) REFERENCES candidate_profile(id, user_id) ON DELETE CASCADE
);

CREATE INDEX outreach_draft_user_recruiter_created_idx
    ON outreach_draft (user_id, recruiter_id, created_at DESC);

ALTER TABLE outreach_draft ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_draft FORCE ROW LEVEL SECURITY;
CREATE POLICY outreach_draft_tenant_policy ON outreach_draft
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
