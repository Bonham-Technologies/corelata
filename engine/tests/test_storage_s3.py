import io

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from corelata.config import S3StorageConfig
from corelata.storage import ProbeLeftover, S3Storage, StorageError, build_storage, describe_storage

BUCKET = "corelata-files"


@pytest.fixture
def s3(monkeypatch, hermetic_aws):
    monkeypatch.setenv("CORELATA_S3_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("CORELATA_S3_SECRET_ACCESS_KEY", "test-secret")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield


def _cfg(**kw) -> S3StorageConfig:
    return S3StorageConfig.model_validate({"kind": "s3", "bucket": BUCKET, **kw})


def test_put_get_overwrite(s3):
    store = S3Storage(_cfg())
    store.put("projects/p1/documents/d1/story.txt", b"one")
    store.put("projects/p1/documents/d1/story.txt", b"two")
    assert store.get("projects/p1/documents/d1/story.txt") == b"two"


def test_prefix_is_prepended(s3):
    S3Storage(_cfg(prefix="preview")).put("a/b.txt", b"x")
    got = boto3.client("s3", region_name="us-east-1").get_object(
        Bucket=BUCKET, Key="preview/a/b.txt"
    )
    assert got["Body"].read() == b"x"


def test_local_file_keeps_the_suffix_and_is_removed(s3):
    store = S3Storage(_cfg())
    store.put("d/report.docx", b"PK\x03\x04")
    with store.local_file("d/report.docx") as path:
        assert path.suffix == ".docx"
        assert path.read_bytes() == b"PK\x03\x04"
    assert not path.exists()


def test_local_file_streams_the_object_without_reading_it_into_memory(s3, monkeypatch):
    """CRL-85: add_source parses every upload through local_file right after the streamed put,
    so it copies the body to the temp file in chunks instead of going through get()."""
    store = S3Storage(_cfg(prefix="pv"))
    body = bytes(range(256)) * (9 * 4096)  # 9 MiB
    store.put("d/big.pdf", io.BytesIO(body))

    def no_get(key: str) -> bytes:
        raise AssertionError("local_file read the whole object through get()")

    monkeypatch.setattr(store, "get", no_get)
    with store.local_file("d/big.pdf") as path:
        assert path.suffix == ".pdf"
        assert path.read_bytes() == body
    assert not path.exists()


def test_local_file_failures_are_storage_errors(s3):
    missing_bucket = S3Storage(_cfg(bucket="no-such-bucket"))
    with (
        pytest.raises(StorageError, match="cannot read a.txt: .*NoSuchBucket"),
        missing_bucket.local_file("a.txt"),
    ):
        pass
    with (
        pytest.raises(StorageError, match="invalid storage key"),
        S3Storage(_cfg()).local_file("../a.txt"),
    ):
        pass


def test_missing_key(s3):
    store = S3Storage(_cfg())
    with pytest.raises(StorageError, match="stored file not found: nope.txt"):
        store.get("nope.txt")
    with pytest.raises(StorageError, match="stored file not found"), store.local_file("x.txt"):
        pass


@pytest.mark.parametrize("key", ["", "/etc/passwd", "../x", "a/../../x", "a\\b", "a//b", "a/./b"])
def test_unsafe_keys_are_rejected(s3, key):
    with pytest.raises(StorageError, match="invalid storage key"):
        S3Storage(_cfg()).put(key, b"x")


def test_delete_prefix_removes_the_key_and_everything_under_it(s3):
    store = S3Storage(_cfg())
    for key in ["p/1/a.txt", "p/1/b/c.txt", "p/1", "p/10/keep.txt"]:
        store.put(key, b"x")
    store.delete_prefix("p/1/")
    assert store.get("p/10/keep.txt") == b"x"
    for gone in ["p/1/a.txt", "p/1/b/c.txt", "p/1"]:
        with pytest.raises(StorageError):
            store.get(gone)


def test_delete_prefix_pages_through_many_keys(s3):
    store = S3Storage(_cfg())
    for i in range(1005):  # more than one list page and one delete batch (1000)
        store.put(f"many/{i}.txt", b"x")
    store.delete_prefix("many")
    listed = boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket=BUCKET)
    assert listed.get("KeyCount", 0) == 0


def test_check_writable_and_failures(s3):
    S3Storage(_cfg()).check_writable()
    with pytest.raises(StorageError, match="storage bucket no-such-bucket .* is not writable"):
        S3Storage(_cfg(bucket="no-such-bucket")).check_writable()
    with pytest.raises(StorageError, match="cannot store a.txt"):
        S3Storage(_cfg(bucket="no-such-bucket")).put("a.txt", b"x")
    with pytest.raises(StorageError, match="cannot read a.txt"):
        S3Storage(_cfg(bucket="no-such-bucket")).get("a.txt")
    with pytest.raises(StorageError, match="cannot delete a/"):
        S3Storage(_cfg(bucket="no-such-bucket")).delete_prefix("a/")


def test_missing_credentials_are_a_storage_error(s3, monkeypatch):
    monkeypatch.delenv("CORELATA_S3_SECRET_ACCESS_KEY")
    with pytest.raises(StorageError, match="CORELATA_S3_SECRET_ACCESS_KEY is not set"):
        S3Storage(_cfg())


def test_build_and_describe(s3):
    cfg = _cfg(endpoint_url="https://ref.storage.supabase.co/storage/v1/s3", prefix="pv")
    assert isinstance(build_storage(cfg), S3Storage)
    assert describe_storage(cfg) == (
        "s3://corelata-files/pv at https://ref.storage.supabase.co/storage/v1/s3"
    )
    assert describe_storage(_cfg()) == "s3://corelata-files"


class _StubPaginator:
    def paginate(self, **_):
        return [{"Contents": [{"Key": "p/1/a.txt"}, {"Key": "p/1/b/c.txt"}]}]


class _SupabaseLikeClient:
    """Supabase's S3 API refuses DeleteObjects (400, empty body) whatever its parameters, and
    deletes single objects fine (checked against the preview's bucket)."""

    def __init__(self, deny: str | None = None):
        self.deleted: list[str] = []
        self.deny = deny

    def get_paginator(self, _):
        return _StubPaginator()

    def delete_objects(self, **_):
        raise ClientError(
            {"Error": {}, "ResponseMetadata": {"HTTPStatusCode": 400}}, "DeleteObjects"
        )

    def delete_object(self, *, Bucket, Key):
        if Key == self.deny:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "DeleteObject"
            )
        self.deleted.append(Key)


def test_delete_prefix_works_where_deleteobjects_is_refused():
    client = _SupabaseLikeClient()
    S3Storage(_cfg(), client=client).delete_prefix("p/1/")
    assert client.deleted == ["p/1", "p/1/a.txt", "p/1/b/c.txt"]


def test_delete_prefix_reports_a_refused_delete():
    store = S3Storage(_cfg(), client=_SupabaseLikeClient(deny="p/1/a.txt"))
    with pytest.raises(StorageError, match="cannot delete p/1/: .*Access Denied"):
        store.delete_prefix("p/1/")


def test_without_the_s3_extra_s3_storage_says_what_to_install(s3, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_boto3(name, *args, **kwargs):
        if name == "boto3" or name.startswith("botocore"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_boto3)
    with pytest.raises(
        StorageError, match=r"S3 storage needs the s3 extra: install corelata\[s3\]"
    ):
        S3Storage(_cfg())


@pytest.fixture
def machine_aws_config(monkeypatch, tmp_path):
    """A developer's AWS setup (CRL-45): a config whose s3 settings botocore merges into every
    client, a profile, and checksum variables. Listed before `s3`, so it is in place first."""
    config = tmp_path / "aws-config"
    config.write_text(
        "[default]\ns3 =\n  payload_signing_enabled = false\n"
        "[profile dev]\ns3 =\n  payload_signing_enabled = false\n"
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_PROFILE", "dev")
    monkeypatch.setenv("AWS_REQUEST_CHECKSUM_CALCULATION", "when_supported")
    monkeypatch.setenv("AWS_RESPONSE_CHECKSUM_VALIDATION", "when_supported")


def test_the_s3_tests_ignore_the_machines_aws_config(machine_aws_config, s3):
    config = S3Storage(_cfg())._s3.meta.config
    assert config.s3 == {"addressing_style": "path"}
    assert config.request_checksum_calculation == "when_required"


def test_checksums_are_only_sent_and_checked_where_s3_requires_them(s3):
    config = S3Storage(_cfg())._s3.meta.config
    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"
    assert config.s3 == {"addressing_style": "path"}


# Corelata's own: list_keys (the Storage protocol has it; the worker clears stale exports).


@pytest.mark.parametrize("prefix", ["", "demo", "/demo/"])
def test_list_keys_matches_local_storage(s3, tmp_path, prefix):
    from corelata.storage import LocalStorage

    stores = [S3Storage(_cfg(prefix=prefix)), LocalStorage(tmp_path)]
    for store in stores:
        for key in ["runs/r1/report.json", "runs/r1/sub/a.txt", "runs/r10/keep.txt", "runs/r1"]:
            if not (store is stores[1] and key == "runs/r1"):  # a file and a directory locally
                store.put(key, b"x")
    s3_keys, local_keys = (store.list_keys("runs/r1/") for store in stores)
    assert s3_keys == local_keys == ["runs/r1/report.json", "runs/r1/sub/a.txt"]
    assert stores[0].list_keys("runs/none") == stores[1].list_keys("runs/none") == []


def test_list_keys_pages_through_many_keys(s3):
    store = S3Storage(_cfg())
    for i in range(1005):  # more than one list page (1000)
        store.put(f"many/{i:04}.txt", b"x")
    keys = store.list_keys("many")
    assert len(keys) == 1005 and keys[0] == "many/0000.txt" and keys == sorted(keys)


def test_list_keys_failures(s3):
    with pytest.raises(StorageError, match="invalid storage key"):
        S3Storage(_cfg()).list_keys("../x")
    with pytest.raises(StorageError, match="cannot list runs/: .*NoSuchBucket"):
        S3Storage(_cfg(bucket="no-such-bucket")).list_keys("runs/")


# CRL-73: an upload reaches the bucket from the file it was spooled to, not from one bytes object.


def _sent_headers(store: S3Storage) -> list[tuple[str, dict[str, str]]]:
    sent: list[tuple[str, dict[str, str]]] = []

    def record(request, **_):
        sent.append((request.method, {k.lower(): v for k, v in request.headers.items()}))

    store._s3.meta.events.register("before-send.s3", record)
    return sent


def test_put_from_a_file_like(s3):
    store = S3Storage(_cfg(prefix="pv"))
    sent = _sent_headers(store)
    f = io.BytesIO(b"skip:Varna port grew.")
    f.seek(5)  # from where the file stands, as LocalStorage does
    store.put("projects/p1/sources/s1/a.txt", f)
    assert store.get("projects/p1/sources/s1/a.txt") == b"Varna port grew."
    assert [method for method, _ in sent] == ["PUT", "GET"]
    assert not any(k.startswith("x-amz-checksum") for _, h in sent for k in h)


def test_a_large_file_like_goes_up_in_parts_without_checksums(s3):
    store = S3Storage(_cfg())
    sent = _sent_headers(store)
    body = bytes(range(256)) * (9 * 4096)  # 9 MiB: over boto3's 8 MiB multipart threshold
    store.put("big.bin", io.BytesIO(body))
    assert store.get("big.bin") == body
    assert [m for m, _ in sent].count("PUT") == 2  # two UploadPart calls
    for _, headers in sent:
        assert not any(k.startswith("x-amz-checksum") for k in headers)
        assert "x-amz-sdk-checksum-algorithm" not in headers


def test_put_from_a_file_like_failure_is_a_storage_error(s3):
    with pytest.raises(StorageError, match="cannot store a.txt: .*NoSuchBucket"):
        S3Storage(_cfg(bucket="no-such-bucket")).put("a.txt", io.BytesIO(b"x"))
    with pytest.raises(StorageError, match="invalid storage key"):
        S3Storage(_cfg()).put("../a.txt", io.BytesIO(b"x"))


def test_the_client_is_built_from_its_own_session_not_boto3_defaults(s3, monkeypatch):
    """CRL-59: storage calls run in worker threads; boto3's default session is not thread-safe
    to create clients from, so S3Storage builds its own."""

    def no_default_session(*args, **kwargs):
        raise AssertionError("S3Storage used boto3's default session")

    monkeypatch.setattr(boto3, "client", no_default_session)
    store = S3Storage(_cfg())
    store.put("a.txt", b"x")
    assert store.get("a.txt") == b"x"
    store.check_writable()


def test_a_probe_whose_delete_fails_is_reported_with_its_key(s3):
    class Stuck:
        def put_object(self, **kw):
            pass

        def delete_object(self, **kw):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "DeleteObject")

    with pytest.raises(ProbeLeftover, match=r"preview/\.corelata-check-[0-9a-f]+") as raised:
        S3Storage(_cfg(prefix="preview"), client=Stuck()).check_writable()
    assert raised.value.key.startswith("preview/.corelata-check-")
