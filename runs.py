"""Write load attempts to the runs table.

Every load records a row, ok or failed, so a job that quietly stopped shows up instead of
leaving no trace. Use it around a load:

    with runs.record(conn, "bulk", "2024q1") as run:
        ...
        run.rows_read = 406184
        run.rows_new = 10308028
"""

import db

# the plan treats three failed runs in a row as the alert, since one can just be a bad
# night for the api
ALERT_AFTER = 3


class Run:
    def __init__(self, conn, run_id):
        self.conn = conn
        self.run_id = run_id
        self.rows_read = None
        self.rows_new = None

    def finish(self, status="ok"):
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE runs
                   SET rows_read = %s, rows_new = %s, status = %s, finished_at = now()
                   WHERE run_id = %s""",
                (self.rows_read, self.rows_new, status, self.run_id),
            )
        self.conn.commit()


class record:
    """Context manager that closes the run either way.

    A failure is recorded rather than swallowed, because the point of the table is that a
    stopped job is visible afterwards.
    """

    def __init__(self, conn, source, detail=None):
        self.conn = conn
        self.source = source
        self.detail = detail
        self.run = None

    def __enter__(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (source, detail, status) VALUES (%s, %s, %s) RETURNING run_id",
                (self.source, self.detail, "running"),
            )
            run_id = cur.fetchone()[0]
        self.conn.commit()
        self.run = Run(self.conn, run_id)
        return self.run

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.run.finish("ok")
            return False
        # the traceback still wants to propagate, so record and let it
        try:
            self.run.finish(f"failed: {type(value).__name__}: {value}"[:500])
        except Exception:
            self.conn.rollback()
        return False


def recent(conn, limit=15):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT run_id, started_at, source, detail, rows_read, rows_new, status,
                      finished_at - started_at AS took
               FROM runs ORDER BY run_id DESC LIMIT %s""",
            (limit,),
        )
        return cur.fetchall()


def consecutive_failures(conn):
    """How many of the most recent runs in a row failed."""
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM runs ORDER BY run_id DESC LIMIT 20")
        count = 0
        for (status,) in cur.fetchall():
            if status == "ok":
                break
            count += 1
    return count


def last_ok(conn, source=None):
    with conn.cursor() as cur:
        if source:
            cur.execute(
                "SELECT started_at FROM runs WHERE status = 'ok' AND source = %s "
                "ORDER BY run_id DESC LIMIT 1",
                (source,),
            )
        else:
            cur.execute(
                "SELECT started_at FROM runs WHERE status = 'ok' ORDER BY run_id DESC LIMIT 1"
            )
        row = cur.fetchone()
    return row[0] if row else None


def show(conn, limit=15):
    rows = recent(conn, limit)
    if not rows:
        print("no runs recorded yet")
        return 0

    print(f"{'id':>5}  {'started':<20}  {'source':<5}  {'detail':<12}  "
          f"{'read':>10}  {'new':>11}  {'took':<10}  status")
    for run_id, started, source, detail, read, new, status, took in rows:
        read_text = "-" if read is None else f"{read:,}"
        new_text = "-" if new is None else f"{new:,}"
        print(f"{run_id:>5}  {started:%Y-%m-%d %H:%M:%S}  {source:<5}  "
              f"{(detail or '-'):<12}  {read_text:>10}  {new_text:>11}  "
              f"{str(took or '-'):<10}  {status}")

    failures = consecutive_failures(conn)
    if failures:
        level = "ALERT" if failures >= ALERT_AFTER else "warning"
        print()
        print(f"{level}: the last {failures} run(s) failed")
    last = last_ok(conn)
    if last:
        print(f"last successful run: {last:%Y-%m-%d %H:%M:%S}")
    return 0


def main(limit=15):
    conn = db.connect()
    code = show(conn, limit)
    conn.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
