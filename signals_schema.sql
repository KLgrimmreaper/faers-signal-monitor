-- the cloud side. only the computed signals are published here, never the raw records,
-- because a year of reports does not fit in a free tier and a signal table does.

CREATE TABLE IF NOT EXISTS signals (
    run_date       DATE NOT NULL,
    drug           TEXT NOT NULL,
    reaction       TEXT NOT NULL,
    reports_both   INTEGER NOT NULL,
    prr            DOUBLE PRECISION,
    ror            DOUBLE PRECISION,
    drug_total     INTEGER NOT NULL,
    reaction_total INTEGER NOT NULL,
    total_reports  INTEGER NOT NULL,
    PRIMARY KEY (run_date, drug, reaction)
);

CREATE INDEX IF NOT EXISTS signals_drug     ON signals (drug);
CREATE INDEX IF NOT EXISTS signals_reaction ON signals (reaction);
