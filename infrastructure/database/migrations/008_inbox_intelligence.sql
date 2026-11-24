ALTER TABLE email_message
    ADD COLUMN classification JSONB,
    ADD COLUMN classification_model TEXT,
    ADD COLUMN classified_at TIMESTAMPTZ,
    ADD COLUMN feedback_category TEXT CHECK (
        feedback_category IS NULL OR feedback_category IN (
            'positive_interest', 'request_information', 'referral', 'not_interested',
            'out_of_office', 'automated', 'unclear'
        )
    ),
    ADD COLUMN feedback_at TIMESTAMPTZ;

CREATE INDEX email_message_user_classification_idx
    ON email_message (user_id, classified_at DESC NULLS LAST);

ALTER TABLE email_message
    ADD CONSTRAINT email_message_id_user_key UNIQUE (id, user_id);

CREATE TABLE inbox_feedback (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    email_message_id UUID NOT NULL,
    category TEXT NOT NULL CHECK (
        category IN (
            'positive_interest', 'request_information', 'referral', 'not_interested',
            'out_of_office', 'automated', 'unclear'
        )
    ),
    note TEXT CHECK (note IS NULL OR length(note) <= 1000),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (email_message_id, user_id)
        REFERENCES email_message (id, user_id) ON DELETE CASCADE
);

CREATE INDEX inbox_feedback_user_reviewed_idx
    ON inbox_feedback (user_id, reviewed_at DESC);

ALTER TABLE inbox_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY inbox_feedback_tenant_policy ON inbox_feedback
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
