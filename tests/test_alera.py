from pathlib import Path

import pytest

from alera import FileExplorer
from alera.exceptions import AleraPathError, AleraValidationError


def test_create_read_and_write(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_folder("docs")
    explorer.create_file("docs/a.txt", "hello")
    assert explorer.read_file("docs/a.txt") == "hello"
    explorer.append_file("docs/a.txt", " world")
    assert explorer.read_file("docs/a.txt") == "hello world"
    explorer.write_file("docs/a.txt", "updated")
    assert explorer.read_file("docs/a.txt") == "updated"


def test_binary_file_round_trip(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    payload = bytes(range(256)) + b"\x00\xff\x80\x7f"

    created = explorer.create_binary_file("data.bin", payload)
    assert created == tmp_path / "data.bin"
    assert created.read_bytes() == payload
    assert explorer.read_binary_file("data.bin") == payload

    explorer.append_binary_file("data.bin", b"APPEND\x00\xff")
    assert explorer.read_binary_file("data.bin") == payload + b"APPEND\x00\xff"

    replacement = memoryview(b"\x00\x01\xfe\xff")
    explorer.write_binary_file("data.bin", replacement)
    assert explorer.read_binary_file("data.bin") == b"\x00\x01\xfe\xff"


def test_binary_file_rejects_text(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    with pytest.raises(AleraValidationError):
        explorer.create_binary_file("data.bin", "not bytes")
    with pytest.raises(AleraValidationError):
        explorer.write_binary_file("data.bin", "not bytes")
    with pytest.raises(AleraValidationError):
        explorer.append_binary_file("data.bin", "not bytes")


def test_delete_moves_to_bin_and_restore(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_file("a.txt", "hello")

    deleted = explorer.delete("a.txt")
    assert deleted.parent == tmp_path / ".alera_bin"
    assert deleted.exists()
    assert not (tmp_path / "a.txt").exists()
    assert explorer.list_bin() == [deleted]

    restored = explorer.restore(deleted.name)
    assert restored == tmp_path / "a.txt"
    assert restored.read_text() == "hello"
    assert explorer.list_bin() == []


def test_recursive_delete_and_permanent_delete(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_folder("one/two")
    explorer.create_file("one/two/example.py", "print('ok')")

    deleted = explorer.delete("one")
    assert deleted.exists()
    assert not (tmp_path / "one").exists()

    explorer.bin_delete(deleted.name)
    assert not deleted.exists()

    explorer.create_file("permanent.txt", "gone")
    explorer.perm_delete("permanent.txt")
    assert not (tmp_path / "permanent.txt").exists()


def test_multiple_delete_and_permanent_delete(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_file("a.txt", "a")
    explorer.create_file("b.txt", "b")

    deleted = explorer.deletes(["a.txt", "b.txt"])
    assert len(deleted) == 2
    assert all(item.parent == tmp_path / ".alera_bin" for item in deleted)
    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()

    explorer.spef_delete([item.name for item in deleted])
    assert explorer.list_bin() == []

    explorer.create_file("c.txt", "c")
    explorer.create_file("d.txt", "d")
    explorer.perm_deletes(["c.txt", "d.txt"])
    assert not (tmp_path / "c.txt").exists()
    assert not (tmp_path / "d.txt").exists()


def test_clear_bin(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_file("a.bin", "a")
    explorer.create_file("b.bin", "b")
    explorer.deletes(["a.bin", "b.bin"])
    assert len(explorer.list_bin()) == 2
    explorer.clear_bin()
    assert explorer.list_bin() == []


def test_recursive_search_and_tree(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_folder("one")
    explorer.create_folder("one/two")
    explorer.create_file("one/two/example.py", "print('ok')")
    assert explorer.search("example") == [tmp_path / "one/two/example.py"]
    assert explorer.find_by_extension("py") == [tmp_path / "one/two/example.py"]
    assert "example.py" in explorer.tree()


def test_root_escape_is_rejected(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    with pytest.raises(AleraPathError):
        explorer.read_file("../outside.txt")


def test_list_arguments_are_enforced(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    with pytest.raises(AleraValidationError):
        explorer.deletes("a.txt")


def test_bin_is_hidden_from_normal_listing(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_file("visible.txt", "visible")
    explorer.create_file("deleted.txt", "deleted")
    explorer.delete("deleted.txt")

    assert tmp_path / ".alera_bin" not in explorer.list(include_hidden=True)
    assert explorer.list_files(recursive=True, include_hidden=True) == [tmp_path / "visible.txt"]
