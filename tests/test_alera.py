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


def test_delete_restore(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_file("a.txt", "hello")
    deleted = explorer.delete("a.txt")
    assert not (tmp_path / "a.txt").exists()
    assert deleted.exists()
    restored = explorer.restore(deleted.name)
    assert restored.exists()
    assert restored.read_text() == "hello"


def test_permanent_bin_delete(tmp_path: Path):
    explorer = FileExplorer(tmp_path)
    explorer.create_file("a.txt", "hello")
    deleted = explorer.delete("a.txt")
    explorer.bin_delete(deleted.name)
    assert not deleted.exists()


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
