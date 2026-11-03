import hashlib
from pathlib import Path

from app.data import ingest
from app.data_quality import profile_dataset
from shared.store import Store


ROOT = Path(__file__).resolve().parents[1]


def test_profile_and_lineage_for_open_regression_fixture(tmp_path):
    raw = (ROOT / "tests/fixtures/regression_sales.csv").read_bytes()
    store = Store(tmp_path / "state.sqlite3")
    dataset = ingest(tmp_path, store, "regression_sales.csv", raw, "tenant-a")
    profile = profile_dataset(tmp_path / f"{dataset['id']}.duckdb", dataset["schema"])
    assert profile["rows"] == dataset["rows"]
    assert len(profile["fields"]) == len(dataset["schema"])
    with store.connect() as db:
        lineage = db.execute(
            "SELECT tenant_id,source_name,source_sha256,row_count,column_count "
            "FROM dataset_lineage WHERE dataset_id=?",
            (dataset["id"],),
        ).fetchone()
    assert tuple(lineage) == (
        "tenant-a",
        "regression_sales.csv",
        hashlib.sha256(raw).hexdigest(),
        dataset["rows"],
        len(dataset["schema"]),
    )
