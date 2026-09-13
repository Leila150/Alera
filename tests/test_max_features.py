from pathlib import Path

from alera import Alera, AleraRuntime, AleraStorage, HiddenConfig, OperationEngine, VirtualFileSystem


def test_internal_storage_creates_central_layout(tmp_path: Path):
    storage = AleraStorage(tmp_path)
    assert storage.root == tmp_path / ".alera"
    assert storage.path("bin").is_dir()
    assert storage.path("hidden").is_dir()
    assert storage.path("index").is_dir()
    assert storage.path("database").is_dir()
    assert storage.path("recovery").is_dir()
    assert storage.path("crash_logs").is_dir()


def test_hidden_config_defaults_and_persistence(tmp_path: Path):
    config = HiddenConfig(tmp_path / ".alera/config/experimental.json")
    assert config.enabled is True
    assert config.storage == "internal"
    config.update(storage="android", enabled=False)
    loaded = HiddenConfig(config.path).load()
    assert loaded.enabled is False
    assert loaded.storage == "android"
    loaded.reset()
    assert loaded.enabled is True
    assert loaded.storage == "internal"


def test_hidden_files_use_internal_vault_by_default(tmp_path: Path):
    a = Alera(tmp_path)
    created = a.hidden.create_hidden_file("secret.txt", "hidden")
    assert created == tmp_path / "secret.txt"
    assert not created.exists()
    assert a.hidden.verify_hidden(created)
    assert a.internal.path("hidden").is_dir()
    assert len(a.hidden.list_hidden()) == 1
    a.hidden.unhide(created)
    assert created.read_text(encoding="utf-8") == "hidden"
    a.close()


def test_hidden_config_live_disable(tmp_path: Path):
    a = Alera(tmp_path)
    assert a.hidden_config.enabled is True
    a.hidden_config.update(enabled=False)
    assert a.hidden.enabled is False
    try:
        a.hidden.list_hidden()
    except RuntimeError:
        pass
    else:
        raise AssertionError("disabled hidden storage should reject operations")
    a.close()


def test_operation_engine_history_and_listener():
    engine = OperationEngine(history_limit=10)
    received = []
    engine.on("create", received.append)
    event = engine.emit("create", "hello.txt", size=5)
    assert received == [event]
    assert engine.history("create") == [event]
    assert engine.statistics()["events"] == 1


def test_runtime_diagnostics_and_lifecycle(tmp_path: Path):
    a = Alera(tmp_path)
    assert isinstance(a.runtime, AleraRuntime)
    diagnostics = a.diagnostics(include_services=False)
    assert diagnostics["ok"] is True
    assert diagnostics["internal"]["root"] == str(tmp_path / ".alera")
    assert diagnostics["capabilities"]["filesystem"]["replace"] is True
    assert a.runtime.shutdown_state is False
    a.close()
    assert a.runtime.shutdown_state is True


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
