"""Review Focus 4: starting the demo clean never touches Coglossa's database or bucket, which
share the Supabase project (spec §23.1). Runs in the engine's environment (CI `hosted-modal`)."""

import pytest

import start_clean

CORELATA_URL = "postgresql://postgres.ref:pw@aws-1-ca-central-1.pooler.supabase.com:5432/corelata?sslmode=require"


@pytest.mark.parametrize(
    "url",
    [
        CORELATA_URL.replace("/corelata?", "/postgres?"),  # the project's default: Coglossa's
        CORELATA_URL.replace("/corelata?", "/coglossa?"),
        CORELATA_URL.replace("/corelata?", "/corelata_old?"),
        CORELATA_URL.replace("/corelata?", "?"),  # no database at all
        CORELATA_URL.replace("/corelata?", "/corelata?dbname=postgres&"),  # libpq: the query wins
        CORELATA_URL.replace("/corelata?", "/corelatafoo?"),
        CORELATA_URL.replace("/corelata?", "/%63oglossa?"),  # percent-encoded: coglossa
    ],
)
def test_any_database_but_corelata_is_refused(url):
    with pytest.raises(SystemExit, match="refusing: CORELATA_DATABASE_URL names the database"):
        start_clean.check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        CORELATA_URL.replace("/corelata?", "/corelata?service=x&"),
        CORELATA_URL + "&options=-c%20search_path%3Dcoglossa",
        CORELATA_URL + "&options=-c%20dbname%3Dpostgres",
        CORELATA_URL + "&options=-c%20search-path%3Dcoglossa",  # Postgres reads - as _
        CORELATA_URL + "&options=--search-path%3Dcoglossa",
    ],
)
def test_a_service_or_options_naming_a_database_is_refused(url):
    with pytest.raises(SystemExit, match="refusing: CORELATA_DATABASE_URL"):
        start_clean.check_url(url)


@pytest.mark.parametrize("name", ["PGOPTIONS", "PGSERVICE"])
def test_a_libpq_environment_override_is_refused(monkeypatch, name):
    """libpq would apply these at connect time, so the URL alone is not the whole story (CRL-52)."""
    monkeypatch.setenv(name, "-c search_path=coglossa")
    with pytest.raises(SystemExit, match=f"refusing: {name} is set"):
        start_clean.check_url(CORELATA_URL)


@pytest.mark.parametrize(
    "url",
    [
        CORELATA_URL + "&foo=bar",  # psycopg.ProgrammingError: unknown query parameter
        "postgresql://u:hunter2@host:notaport/corelata",  # a malformed conninfo
        "not a url hunter2",
    ],
)
def test_an_unparsable_url_is_refused_cleanly_without_echoing_it(url):
    with pytest.raises(SystemExit) as raised:
        start_clean.check_url(url)
    message = str(raised.value)
    assert message.startswith("refusing: ") and "hunter2" not in message and "pw" not in message


def test_a_config_error_is_refused_cleanly(monkeypatch):
    import settings

    from corelata.config import ConfigError

    def boom(url):
        raise ConfigError("bad url postgresql://u:secret-pw@h/x")

    monkeypatch.setattr(settings, "check_database_url", boom)
    with pytest.raises(SystemExit) as raised:
        start_clean.check_url(CORELATA_URL)
    assert str(raised.value).startswith("refusing: ") and "secret-pw" not in str(raised.value)


def test_main_turns_a_malformed_url_into_a_refusal(monkeypatch):
    monkeypatch.setenv("CORELATA_S3_ENDPOINT", "https://ref.storage.supabase.co/storage/v1/s3")
    monkeypatch.setenv("CORELATA_S3_REGION", "ca-central-1")
    monkeypatch.setenv("CORELATA_DATABASE_URL", CORELATA_URL + "&foo=bar")
    with pytest.raises(SystemExit, match="refusing: "):
        start_clean.main(["--yes"])


def test_the_corelata_database_is_accepted():
    start_clean.check_url(CORELATA_URL)
    start_clean.check_url(CORELATA_URL.replace("/corelata?", "/%63orelata?"))  # decodes to corelata


class FakeConnection:
    def __init__(self, database: str) -> None:
        self.database = database
        self.statements: list[str] = []
        self.committed = False

    def execute(self, statement: str):
        self.statements.append(statement)
        return self

    def fetchone(self):
        return (self.database,)

    def commit(self) -> None:
        self.committed = True


def test_a_connection_to_another_database_truncates_nothing():
    conn = FakeConnection("postgres")
    with pytest.raises(SystemExit, match="refusing: connected to the database 'postgres'"):
        start_clean.clear_database(conn)
    assert conn.statements == ["SELECT current_database()"] and not conn.committed


def test_the_corelata_database_loses_its_rows_and_keeps_its_schema():
    conn = FakeConnection("corelata")
    assert start_clean.clear_database(conn) == len(start_clean.tables())
    truncate = conn.statements[1]
    assert truncate.startswith("TRUNCATE ") and truncate.endswith(" RESTART IDENTITY CASCADE")
    for table in ("project", "run", "source", "procrastinate_jobs", "procrastinate_workers"):
        assert f" {table}," in truncate or f" {table} " in truncate
    assert "alembic_version" not in truncate and conn.committed


@pytest.fixture
def buckets(monkeypatch):
    import boto3
    from moto import mock_aws

    monkeypatch.setenv("CORELATA_S3_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("CORELATA_S3_SECRET_ACCESS_KEY", "s")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        for bucket in ("corelata-files", "coglossa-files"):
            s3.create_bucket(Bucket=bucket)
            for key in ("projects/p/sources/s/a.txt", "runs/r/report.json"):
                s3.put_object(Bucket=bucket, Key=key, Body=b"x")
        yield s3


def _storage(bucket):
    from corelata.config import S3StorageConfig
    from corelata.storage import S3Storage

    return S3Storage(S3StorageConfig(kind="s3", bucket=bucket))


def test_the_bucket_is_emptied_and_coglossas_is_left_alone(buckets):
    assert start_clean.clear_bucket(_storage("corelata-files")) == 2
    assert buckets.list_objects_v2(Bucket="corelata-files").get("KeyCount") == 0
    assert buckets.list_objects_v2(Bucket="coglossa-files")["KeyCount"] == 2


def test_doctor_probes_at_the_root_are_removed_and_other_root_keys_stay(buckets):
    for key in (".corelata-check-abc123", ".corelata-check-def456", "keep.txt", ".other"):
        buckets.put_object(Bucket="corelata-files", Key=key, Body=b"")
    start_clean.clear_bucket(_storage("corelata-files"))
    left = [o["Key"] for o in buckets.list_objects_v2(Bucket="corelata-files")["Contents"]]
    assert sorted(left) == [".other", "keep.txt"]


def test_another_bucket_is_refused(buckets):
    with pytest.raises(SystemExit, match="refusing: the bucket is 'coglossa-files'"):
        start_clean.clear_bucket(_storage("coglossa-files"))
    assert buckets.list_objects_v2(Bucket="coglossa-files")["KeyCount"] == 2


def test_main_checks_before_it_connects(monkeypatch):
    for name in ("CORELATA_DATABASE_URL", "CORELATA_S3_ENDPOINT", "CORELATA_S3_REGION"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="CORELATA_DATABASE_URL, .* not set"):
        start_clean.main(["--yes"])
    monkeypatch.setenv("CORELATA_S3_ENDPOINT", "https://ref.storage.supabase.co/storage/v1/s3")
    monkeypatch.setenv("CORELATA_S3_REGION", "ca-central-1")
    monkeypatch.setenv("CORELATA_DATABASE_URL", CORELATA_URL.replace("/corelata?", "/postgres?"))
    with pytest.raises(SystemExit, match="refusing"):
        start_clean.main(["--yes"])
    monkeypatch.setenv("CORELATA_DATABASE_URL", CORELATA_URL)
    with pytest.raises(SystemExit, match="add --yes"):
        start_clean.main([])
