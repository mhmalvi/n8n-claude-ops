-- Tables the workflows write to. Run once against the database behind the "Ops Postgres" credential.

CREATE TABLE IF NOT EXISTS ops_incidents (
    id            bigserial PRIMARY KEY,
    fingerprint   text        NOT NULL,          -- same workflow + node + error shape => same value
    source        text        NOT NULL,
    workflow_name text        NOT NULL,
    failed_node   text        NOT NULL DEFAULT '',
    severity      text        NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    category      text        NOT NULL,
    summary       text        NOT NULL,
    fix_note      text        NOT NULL,
    classifier_ok boolean     NOT NULL,          -- false = Claude failed and the fallback escalated it
    received_at   timestamptz NOT NULL,
    logged_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ops_incidents_fingerprint ON ops_incidents (fingerprint, received_at DESC);

-- How often each failure repeats: the first thing to look at in a weekly review.
CREATE OR REPLACE VIEW ops_incident_repeats AS
SELECT fingerprint, workflow_name, failed_node, count(*) AS occurrences,
       max(severity) AS any_severity, max(received_at) AS last_seen
FROM ops_incidents GROUP BY fingerprint, workflow_name, failed_node;

CREATE TABLE IF NOT EXISTS crm_leads (
    id           bigserial PRIMARY KEY,
    email        text        NOT NULL UNIQUE,
    name         text        NOT NULL DEFAULT '',
    company      text        NOT NULL DEFAULT '',
    intent       text        NOT NULL,
    priority     text        NOT NULL,
    lead_score   int         NOT NULL CHECK (lead_score BETWEEN 0 AND 100),
    last_summary text        NOT NULL,
    reply_draft  text        NOT NULL,           -- a draft for a human to review, never auto-sent
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inbox_triage_log (
    id            bigserial PRIMARY KEY,
    from_email    text        NOT NULL,
    channel       text        NOT NULL,
    subject       text        NOT NULL,
    intent        text        NOT NULL,
    priority      text        NOT NULL,
    lead_score    int         NOT NULL,
    summary       text        NOT NULL,
    classifier_ok boolean     NOT NULL,
    received_at   timestamptz NOT NULL,
    logged_at     timestamptz NOT NULL DEFAULT now()
);
