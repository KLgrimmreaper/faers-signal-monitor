-- Milestone 2. Only what the milestone needs: the events table and the indexes
-- that milestone 3 will want. The runs table is milestone 7 and the materialized
-- marginals are milestone 6, so they are not here yet.

CREATE TABLE IF NOT EXISTS events (
    report_id     TEXT NOT NULL,
    drug          TEXT NOT NULL,          -- normalised
    drug_raw      TEXT NOT NULL,          -- as received, for auditing the normalisation
    reaction      TEXT NOT NULL,          -- MedDRA preferred term, normalised
    serious       BOOLEAN,
    received_date DATE,
    -- Re-ingesting the same reports conflicts on this key and inserts nothing,
    -- which is the whole idempotency story. safetyreportversion is deliberately
    -- not in the key: a later version of a report that repeats a drug+reaction
    -- pair is skipped, but reactions added by a later version are new rows and
    -- still land. See NOTES.md.
    PRIMARY KEY (report_id, drug, reaction)
);

CREATE INDEX IF NOT EXISTS events_drug_reaction ON events (drug, reaction);
CREATE INDEX IF NOT EXISTS events_reaction      ON events (reaction);
CREATE INDEX IF NOT EXISTS events_received_date ON events (received_date);
