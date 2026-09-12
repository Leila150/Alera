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


def test_delete_is_permanent(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_file("a.txt", "hello")
    deleted = explorer.delete("a.txt")
    assert deleted == tmp_path / "a.txt"
    assert not deleted.exists()
    assert not (tmp_path / ".alera_bin").exists()


def test_recursive_permanent_delete(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_folder("one/two")
    explorer.create_file("one/two/example.py", "print('ok')")
    explorer.delete("one")
    assert not (tmp_path / "one").exists()


def test_multiple_permanent_delete(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_file("a.txt", "a")
    explorer.create_file("b.txt", "b")
    deleted = explorer.deletes(["a.txt", "b.txt"])
    assert deleted == [tmp_path / "a.txt", tmp_path / "b.txt"]
    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()


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
