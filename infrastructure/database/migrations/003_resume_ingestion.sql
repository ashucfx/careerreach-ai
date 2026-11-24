CREATE TABLE resume_document (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL CHECK (length(file_name) BETWEEN 1 AND 255),
    content_type TEXT NOT NULL CHECK (
        content_type IN (
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
    ),
    size_bytes INTEGER NOT NULL CHECK (size_bytes BETWEEN 1 AND 5242880),
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    extracted_text TEXT NOT NULL CHECK (length(extracted_text) BETWEEN 1 AND 250000),
    parser_version TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, sha256),
    UNIQUE (id, user_id)
);

CREATE INDEX resume_document_user_uploaded_idx
    ON resume_document (user_id, uploaded_at DESC);

CREATE TABLE resume_extraction (
    id UUID PRIMARY KEY,
    resume_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    extracted_profile JSONB NOT NULL,
    model TEXT NOT NULL CHECK (length(model) BETWEEN 1 AND 200),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (resume_id, version),
    FOREIGN KEY (resume_id, user_id) REFERENCES resume_document(id, user_id) ON DELETE CASCADE
);

CREATE INDEX resume_extraction_user_resume_version_idx
    ON resume_extraction (user_id, resume_id, version DESC);

ALTER TABLE resume_document ENABLE ROW LEVEL SECURITY;
ALTER TABLE resume_document FORCE ROW LEVEL SECURITY;
CREATE POLICY resume_document_tenant_policy ON resume_document
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE resume_extraction ENABLE ROW LEVEL SECURITY;
ALTER TABLE resume_extraction FORCE ROW LEVEL SECURITY;
CREATE POLICY resume_extraction_tenant_policy ON resume_extraction
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
