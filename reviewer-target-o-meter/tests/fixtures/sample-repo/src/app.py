"""Tiny fixture checkout for the F-01 end-to-end smoke.

A one-file repo containing the SQL-string-concatenation pattern the reviewer
should flag. The CLI runs against this directory; the real diff/context/plan
discovery is F-02 — F-01 only proves the pipeline reaches stdout with a valid
report over an accepted input.
"""


def query(user_id: str) -> str:
    # NOTE: user_id is attacker-controlled
    sql = "SELECT * FROM users WHERE id = " + user_id
    return run(sql)


def run(sql: str) -> str:  # pragma: no cover - fixture stub
    raise NotImplementedError(sql)
