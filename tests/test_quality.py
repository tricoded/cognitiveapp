import json

import numpy as np

from pipeline.quality.checks import EXPECTED_FIELDS, check_schema, psi
from pipeline.model.evaluate import at_top, ks_stat


def test_psi_zero_for_same_distribution():
    rng = np.random.default_rng(0)
    a = rng.normal(size=5000)
    assert psi(a, rng.normal(size=5000)) < 0.02


def test_psi_detects_shift():
    rng = np.random.default_rng(0)
    assert psi(rng.normal(size=5000), rng.normal(1.0, size=5000)) > 0.25


def test_schema_contract_flags_renamed_column(tmp_path):
    good = {k: 1 for k in EXPECTED_FIELDS}
    drifted = dict(good)
    drifted["message_length"] = drifted.pop("msg_len")
    for dt, row in [("2026-01-01", good), ("2026-01-02", drifted)]:
        d = tmp_path / f"dt={dt}"
        d.mkdir()
        (d / "part-0000.jsonl").write_text(json.dumps(row) + "\n")
    alerts = check_schema(tmp_path, ["2026-01-01", "2026-01-02", "2026-01-03"])
    by_dt = {a.dt: a for a in alerts}
    assert "2026-01-01" not in by_dt
    assert "msg_len" in by_dt["2026-01-02"].detail and "message_length" in by_dt["2026-01-02"].detail
    assert by_dt["2026-01-03"].detail == "raw partition missing"


def test_ks_and_top_k():
    y = np.array([0, 0, 0, 0, 1, 1])
    s = np.array([0.1, 0.2, 0.3, 0.4, 0.8, 0.9])
    assert ks_stat(y, s) == 1.0
    p, r = at_top(y, s, 2 / 6)
    assert p == 1.0 and r == 1.0
