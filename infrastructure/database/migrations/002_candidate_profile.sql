CREATE TABLE candidate_profile (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    full_name TEXT NOT NULL CHECK (length(full_name) BETWEEN 1 AND 200),
    headline TEXT CHECK (headline IS NULL OR length(headline) <= 300),
    summary TEXT CHECK (summary IS NULL OR length(summary) <= 10000),
    target_titles TEXT[] NOT NULL DEFAULT '{}',
    target_locations TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT candidate_profile_id_user_key UNIQUE (id, user_id)
);

CREATE TABLE candidate_profile_history (
    id UUID PRIMARY KEY,
    profile_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (profile_id, version),
    FOREIGN KEY (profile_id, user_id) REFERENCES candidate_profile(id, user_id) ON DELETE CASCADE
);

CREATE INDEX candidate_profile_history_user_version_idx
    ON candidate_profile_history (user_id, version DESC);

CREATE TABLE candidate_skill (
    id UUID PRIMARY KEY,
    profile_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    proficiency TEXT CHECK (proficiency IN ('beginner', 'intermediate', 'advanced', 'expert')),
    years_experience NUMERIC(4, 1) CHECK (years_experience BETWEEN 0 AND 80),
    FOREIGN KEY (profile_id, user_id) REFERENCES candidate_profile(id, user_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX candidate_skill_profile_name_key
    ON candidate_skill (profile_id, lower(name));

CREATE TABLE candidate_experience (
    id UUID PRIMARY KEY,
    profile_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    employer TEXT NOT NULL CHECK (length(employer) BETWEEN 1 AND 200),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    location TEXT CHECK (location IS NULL OR length(location) <= 200),
    description TEXT CHECK (description IS NULL OR length(description) <= 10000),
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ,
    currently_employed BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT candidate_experience_dates_check
        CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT candidate_experience_current_check
        CHECK (NOT currently_employed OR end_date IS NULL),
    FOREIGN KEY (profile_id, user_id) REFERENCES candidate_profile(id, user_id) ON DELETE CASCADE
);

CREATE INDEX candidate_experience_profile_idx ON candidate_experience (profile_id, start_date DESC);

CREATE TABLE candidate_education (
    id UUID PRIMARY KEY,
    profile_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    institution TEXT NOT NULL CHECK (length(institution) BETWEEN 1 AND 200),
    credential TEXT NOT NULL CHECK (length(credential) BETWEEN 1 AND 200),
    field_of_study TEXT CHECK (field_of_study IS NULL OR length(field_of_study) <= 200),
    start_year INTEGER CHECK (start_year BETWEEN 1900 AND 2100),
    end_year INTEGER CHECK (end_year BETWEEN 1900 AND 2100),
    CONSTRAINT candidate_education_year_check
        CHECK (start_year IS NULL OR end_year IS NULL OR end_year >= start_year),
    FOREIGN KEY (profile_id, user_id) REFERENCES candidate_profile(id, user_id) ON DELETE CASCADE
);

CREATE INDEX candidate_education_profile_idx ON candidate_education (profile_id);

ALTER TABLE candidate_profile ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_profile FORCE ROW LEVEL SECURITY;
CREATE POLICY candidate_profile_tenant_policy ON candidate_profile
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE candidate_profile_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_profile_history FORCE ROW LEVEL SECURITY;
CREATE POLICY candidate_profile_history_tenant_policy ON candidate_profile_history
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE candidate_skill ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_skill FORCE ROW LEVEL SECURITY;
CREATE POLICY candidate_skill_tenant_policy ON candidate_skill
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE candidate_experience ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_experience FORCE ROW LEVEL SECURITY;
CREATE POLICY candidate_experience_tenant_policy ON candidate_experience
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE candidate_education ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_education FORCE ROW LEVEL SECURITY;
CREATE POLICY candidate_education_tenant_policy ON candidate_education
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
