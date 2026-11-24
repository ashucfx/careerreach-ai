CREATE TABLE job_listing (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[a-f0-9]{64}$'),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    company_name TEXT NOT NULL CHECK (length(company_name) BETWEEN 1 AND 200),
    location TEXT CHECK (location IS NULL OR length(location) <= 200),
    source_url TEXT CHECK (source_url IS NULL OR length(source_url) <= 2000),
    description TEXT NOT NULL CHECK (length(description) BETWEEN 100 AND 50000),
    source_captured_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, fingerprint),
    UNIQUE (id, user_id)
);

CREATE INDEX job_listing_user_updated_idx ON job_listing (user_id, updated_at DESC);

CREATE TABLE job_analysis (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    analysis JSONB NOT NULL,
    model TEXT NOT NULL CHECK (length(model) BETWEEN 1 AND 200),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, version),
    UNIQUE (id, user_id),
    FOREIGN KEY (job_id, user_id) REFERENCES job_listing(id, user_id) ON DELETE CASCADE
);

CREATE INDEX job_analysis_user_job_version_idx
    ON job_analysis (user_id, job_id, version DESC);

CREATE TABLE job_requirement (
    id UUID PRIMARY KEY,
    analysis_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    category TEXT NOT NULL CHECK (
        category IN (
            'skill', 'experience', 'education', 'responsibility', 'location',
            'work_authorization', 'compensation', 'other'
        )
    ),
    requirement TEXT NOT NULL CHECK (length(requirement) BETWEEN 1 AND 1000),
    is_required BOOLEAN NOT NULL,
    source_quote TEXT NOT NULL CHECK (length(source_quote) BETWEEN 1 AND 1000),
    UNIQUE (analysis_id, ordinal),
    FOREIGN KEY (analysis_id, user_id) REFERENCES job_analysis(id, user_id) ON DELETE CASCADE
);

CREATE INDEX job_requirement_user_category_idx
    ON job_requirement (user_id, category, is_required);

CREATE TABLE company (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    normalized_name TEXT NOT NULL CHECK (length(normalized_name) BETWEEN 1 AND 200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, normalized_name),
    UNIQUE (id, user_id)
);

CREATE TABLE company_research (
    id UUID PRIMARY KEY,
    company_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    query TEXT NOT NULL CHECK (length(query) BETWEEN 1 AND 500),
    analysis JSONB NOT NULL,
    sources JSONB NOT NULL,
    model TEXT NOT NULL CHECK (length(model) BETWEEN 1 AND 200),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, version),
    FOREIGN KEY (company_id, user_id) REFERENCES company(id, user_id) ON DELETE CASCADE
);

CREATE INDEX company_user_name_idx ON company (user_id, normalized_name);
CREATE INDEX company_research_user_company_version_idx
    ON company_research (user_id, company_id, version DESC);

ALTER TABLE job_listing ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_listing FORCE ROW LEVEL SECURITY;
CREATE POLICY job_listing_tenant_policy ON job_listing
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE job_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_analysis FORCE ROW LEVEL SECURITY;
CREATE POLICY job_analysis_tenant_policy ON job_analysis
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE job_requirement ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_requirement FORCE ROW LEVEL SECURITY;
CREATE POLICY job_requirement_tenant_policy ON job_requirement
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE company ENABLE ROW LEVEL SECURITY;
ALTER TABLE company FORCE ROW LEVEL SECURITY;
CREATE POLICY company_tenant_policy ON company
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE company_research ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_research FORCE ROW LEVEL SECURITY;
CREATE POLICY company_research_tenant_policy ON company_research
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
