-- the events table, plus the marginals the statistics need. those are materialized
-- because computing them per row turns a pair lookup into a full aggregate over ten
-- million rows, which is measured in NOTES.md.

CREATE TABLE IF NOT EXISTS events (
    report_id     TEXT NOT NULL,
    drug          TEXT NOT NULL,          -- normalised
    drug_raw      TEXT NOT NULL,          -- as received, for auditing the normalisation
    reaction      TEXT NOT NULL,          -- MedDRA preferred term, normalised
    serious       BOOLEAN,
    received_date DATE,
    -- re-ingesting the same reports conflicts on this key and inserts nothing, which is
    -- the whole idempotency story. caseversion is deliberately not in the key, so a
    -- follow-up that repeats a pair is skipped while any new reaction still lands
    PRIMARY KEY (report_id, drug, reaction)
);

CREATE INDEX IF NOT EXISTS events_drug_reaction ON events (drug, reaction);
CREATE INDEX IF NOT EXISTS events_reaction      ON events (reaction);
CREATE INDEX IF NOT EXISTS events_received_date ON events (received_date);

-- how many reports mention each drug, and each reaction, plus the report count itself.
-- REFRESH MATERIALIZED VIEW after a load
CREATE MATERIALIZED VIEW IF NOT EXISTS drug_totals AS
    SELECT drug, count(DISTINCT report_id) AS total FROM events GROUP BY drug;

CREATE MATERIALIZED VIEW IF NOT EXISTS reaction_totals AS
    SELECT reaction, count(DISTINCT report_id) AS total FROM events GROUP BY reaction;

CREATE MATERIALIZED VIEW IF NOT EXISTS event_totals AS
    SELECT count(DISTINCT report_id) AS reports FROM events;

CREATE UNIQUE INDEX IF NOT EXISTS drug_totals_drug         ON drug_totals (drug);
CREATE UNIQUE INDEX IF NOT EXISTS reaction_totals_reaction ON reaction_totals (reaction);

-- one row per load attempt, so a job that quietly stopped is visible afterwards. status
-- is 'ok' or the error, which is what makes a failure loud instead of silent
CREATE TABLE IF NOT EXISTS runs (
    run_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_date    DATE NOT NULL DEFAULT current_date,
    source      TEXT NOT NULL,            -- 'api' or 'bulk'
    detail      TEXT,                     -- what was asked for
    rows_read   INTEGER,
    rows_new    INTEGER,
    status      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS runs_started_at ON runs (started_at DESC);
