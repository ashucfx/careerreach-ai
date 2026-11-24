CREATE TABLE recruiter_contact (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    normalized_identity TEXT NOT NULL CHECK (length(normalized_identity) BETWEEN 3 AND 420),
    full_name TEXT NOT NULL CHECK (length(full_name) BETWEEN 2 AND 200),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 2 AND 200),
    company_name TEXT NOT NULL CHECK (length(company_name) BETWEEN 1 AND 200),
    location TEXT CHECK (location IS NULL OR length(location) <= 200),
    profile_url TEXT CHECK (
        profile_url IS NULL OR
        (length(profile_url) <= 2000 AND profile_url ~ '^https?://[^[:space:]]+$')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, normalized_identity),
    UNIQUE (id, user_id)
);

CREATE INDEX recruiter_contact_user_company_idx
    ON recruiter_contact (user_id, lower(company_name), lower(title));

CREATE TABLE contact_source (
    id UUID PRIMARY KEY,
    recruiter_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider = 'brave_search'),
    source_id TEXT NOT NULL CHECK (length(source_id) BETWEEN 1 AND 128),
    source_url TEXT NOT NULL CHECK (length(source_url) BETWEEN 1 AND 2000),
    source_title TEXT NOT NULL CHECK (length(source_title) BETWEEN 1 AND 500),
    source_snippet TEXT NOT NULL CHECK (length(source_snippet) BETWEEN 1 AND 4000),
    source_quote TEXT NOT NULL CHECK (length(source_quote) BETWEEN 1 AND 1000),
    search_query TEXT NOT NULL CHECK (length(search_query) BETWEEN 1 AND 500),
    captured_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recruiter_id, provider, source_id),
    FOREIGN KEY (recruiter_id, user_id)
        REFERENCES recruiter_contact(id, user_id) ON DELETE CASCADE
);

CREATE INDEX contact_source_user_recruiter_captured_idx
    ON contact_source (user_id, recruiter_id, captured_at DESC);

CREATE TABLE candidate_job_match (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL,
    profile_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    profile_version INTEGER NOT NULL CHECK (profile_version > 0),
    version INTEGER NOT NULL CHECK (version > 0),
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    analysis JSONB NOT NULL,
    model TEXT NOT NULL CHECK (length(model) BETWEEN 1 AND 200),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, profile_version, version),
    FOREIGN KEY (job_id, user_id) REFERENCES job_listing(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (profile_id, user_id) REFERENCES candidate_profile(id, user_id) ON DELETE CASCADE
);

CREATE INDEX candidate_job_match_user_job_version_idx
    ON candidate_job_match (user_id, job_id, profile_version, version DESC);

CREATE TABLE candidate_contact_match (
    id UUID PRIMARY KEY,
    recruiter_id UUID NOT NULL,
    job_id UUID NOT NULL,
    profile_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    profile_version INTEGER NOT NULL CHECK (profile_version > 0),
    version INTEGER NOT NULL CHECK (version > 0),
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    rationale TEXT NOT NULL CHECK (length(rationale) BETWEEN 1 AND 2000),
    evidence JSONB NOT NULL,
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

CREATE INDEX candidate_contact_match_user_job_score_idx
    ON candidate_contact_match (user_id, job_id, profile_version, score DESC, created_at DESC);

ALTER TABLE recruiter_contact ENABLE ROW LEVEL SECURITY;
ALTER TABLE recruiter_contact FORCE ROW LEVEL SECURITY;
CREATE POLICY recruiter_contact_tenant_policy ON recruiter_contact
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE contact_source ENABLE ROW LEVEL SECURITY;
ALTER TABLE contact_source FORCE ROW LEVEL SECURITY;
CREATE POLICY contact_source_tenant_policy ON contact_source
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE candidate_job_match ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_job_match FORCE ROW LEVEL SECURITY;
CREATE POLICY candidate_job_match_tenant_policy ON candidate_job_match
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE candidate_contact_match ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_contact_match FORCE ROW LEVEL SECURITY;
CREATE POLICY candidate_contact_match_tenant_policy ON candidate_contact_match
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
