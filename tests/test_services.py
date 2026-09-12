from pathlib import Path

from alera import BackupManager, CleanupManager, FileDatabase, FileInspector, StorageCalculator, VersionManager


def test_inspector_and_calculator(tmp_path: Path):
    path = tmp_path / "data.txt"
    path.write_text("hello world\n")
    info = FileInspector(tmp_path).inspect("data.txt")
    assert info["type"] == "text/data"
    assert info["size"] == path.stat().st_size
    assert StorageCalculator.parse("1 KB") == 1024
    assert StorageCalculator.humanize(1024) == "1.00 KB"


def test_versions_do_not_reuse_deleted_numbers(tmp_path: Path):
    target = tmp_path / "data.txt"
    target.write_text("one")
    versions = VersionManager(tmp_path)
    assert versions.create("data.txt") == 1
    target.write_text("two")
    assert versions.create("data.txt") == 2
    versions.delete("data.txt", 1)
    target.write_text("three")
    assert versions.create("data.txt") == 3


def test_backup_rejects_nested_destination(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("a")
    manager = BackupManager(tmp_path)
    try:
        manager.create("source", "source/backup")
    except ValueError:
        pass
    else:
        raise AssertionError("nested backup destination should be rejected")


def test_cleanup_configuration_is_safe_by_default(tmp_path: Path):
    (tmp_path / "empty.txt").touch()
    cleaner = CleanupManager(tmp_path)
    assert cleaner.preview()["empty_files"] == []
    cleaner.configure(empty_files=True)
    assert str(tmp_path / "empty.txt") in cleaner.preview()["empty_files"]


def test_database_index(tmp_path: Path):
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    database = FileDatabase(tmp_path)
    assert database.index() == 2
    assert len(database.duplicates()) == 1
