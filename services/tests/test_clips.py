"""Файловое хранилище клипов ``FileClipStorage``."""

import pytest

from services.clips import FileClipStorage

PAYLOAD = b'{"version": 1, "gloss": "UCH"}'


@pytest.fixture
def storage(tmp_path):
    return FileClipStorage(root=tmp_path, url="/media/")


def test_save_and_read_roundtrip(storage):
    path = storage.save("clips/2026/10/uch.json.gz", PAYLOAD)

    assert path == "clips/2026/10/uch.json.gz"
    assert storage.exists(path)
    assert storage.read(path) == PAYLOAD


def test_save_creates_parent_directories(storage, tmp_path):
    storage.save("clips/2026/10/nested/uch.json.gz", PAYLOAD)

    assert (tmp_path / "clips/2026/10/nested/uch.json.gz").is_file()


def test_exists_is_false_for_missing_file(storage):
    assert not storage.exists("clips/missing.json.gz")


def test_read_missing_file_raises(storage):
    with pytest.raises(FileNotFoundError):
        storage.read("clips/missing.json.gz")


def test_open_returns_readable_stream(storage):
    storage.save("clips/uch.json.gz", PAYLOAD)

    with storage.open("clips/uch.json.gz") as stream:
        assert stream.read() == PAYLOAD


def test_size_reports_bytes(storage):
    storage.save("clips/uch.json.gz", PAYLOAD)

    assert storage.size("clips/uch.json.gz") == len(PAYLOAD)


def test_delete_removes_file(storage):
    storage.save("clips/uch.json.gz", PAYLOAD)

    storage.delete("clips/uch.json.gz")

    assert not storage.exists("clips/uch.json.gz")


def test_delete_missing_file_is_noop(storage):
    storage.delete("clips/missing.json.gz")


def test_etag_is_stable_for_same_content(storage):
    storage.save("clips/a.json.gz", PAYLOAD)
    storage.save("clips/b.json.gz", PAYLOAD)

    assert storage.etag("clips/a.json.gz") == storage.etag("clips/b.json.gz")


def test_etag_changes_with_content(storage):
    storage.save("clips/a.json.gz", PAYLOAD)
    storage.save("clips/b.json.gz", PAYLOAD + b" ")

    assert storage.etag("clips/a.json.gz") != storage.etag("clips/b.json.gz")


def test_etag_is_quoted(storage):
    storage.save("clips/a.json.gz", PAYLOAD)

    assert storage.etag("clips/a.json.gz").startswith('"')


def test_url_joins_base_and_path(storage):
    assert storage.url("clips/2026/10/uch.json.gz") == "/media/clips/2026/10/uch.json.gz"


def test_url_does_not_duplicate_slash(tmp_path):
    storage = FileClipStorage(root=tmp_path, url="/media/")

    assert storage.url("/clips/a.json.gz") == "/media/clips/a.json.gz"
