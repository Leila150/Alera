from pathlib import Path

from alera import AleraStorage, OperationEngine, VirtualFileSystem


def test_internal_storage_creates_central_layout(tmp_path: Path):
    storage = AleraStorage(tmp_path)
    assert storage.root == tmp_path / ".alera"
    assert storage.path("bin").is_dir()
    assert storage.path("index").is_dir()
    assert storage.path("database").is_dir()
    assert storage.path("recovery").is_dir()


def test_operation_engine_history_and_listener():
    engine = OperationEngine(history_limit=10)
    received = []
    engine.on("create", received.append)
    event = engine.emit("create", "hello.txt", size=5)
    assert received == [event]
    assert engine.history("create") == [event]
    assert engine.statistics()["events"] == 1


def test_virtual_filesystem_max_operations(tmp_path: Path):
    vfs = VirtualFileSystem()
    vfs.create_file("docs/readme.txt", "hello")
    vfs.append("docs/readme.txt", " world")
    assert vfs.read("docs/readme.txt") == "hello world"
    assert vfs.find("*.txt", files_only=True) == ["docs/readme.txt"]
    assert vfs.hash("docs/readme.txt")
    snapshot = vfs.snapshot()
    vfs.create_file("temporary.bin", b"x")
    vfs.restore(snapshot)
    assert not vfs.exists("temporary.bin")
    vfs.export(str(tmp_path / "export"))
    assert (tmp_path / "export/docs/readme.txt").read_text() == "hello world"
