# Alera

A powerful, cross-platform Python filesystem and system-information toolkit.

Alera is designed to make file management feel like a real file explorer while keeping the API typed, safe, modular, observable, and Pythonic.

## 0.5.0 highlights

- Unified `Alera(...)` service hub with lifecycle/context-manager support
- `AleraRuntime` for diagnostics, capabilities, resource usage, service health, benchmarking, events, GC, and graceful shutdown
- Universal power layer applied to every public Alera class: `capabilities()`, `describe()`, `health()`, `snapshot()`, `call()`, `timed()`, `has()`, and `safe()` where not already defined
- Centralized `.alera/` runtime storage with subsystem directories for cache, index, database, recovery, versions, snapshots, transactions, locks, archives, backups, sync, watcher state, security, temp data, logs, and crash logs
- Experimental `hidden_config`: hidden storage enabled by default with Alera's internal `.alera/hidden/` backend; Android shared storage is opt-in
- Automatic crash logging with structured reports and safe shutdown handling
- Advanced `SearchEngine` with metadata, content, hash, MIME, size, fuzzy/ranked, boolean, duplicate, and persistent SQLite index capabilities
- Unified binary filesystem operations through `FileExplorer` / `BinaryFileManager`
- Large archive toolkit covering ZIP/JAR/APK/WAR/EAR/WHL/XPI/CRX/TAR and optional compression backends
- Configurable, opt-in `CleanupManager` with preview/dry-run and exclusions
- Verified `BackupManager` with nested-destination protection and restore verification
- Numbered `VersionManager` snapshots with checksums and atomic manifests
- SQLite `FileDatabase` index with incremental refresh and duplicate lookup
- `FileInspector` with file signatures, encoding detection, entropy, MIME data, and streaming text statistics
- Improved filesystem analytics and storage analysis
- Polling `FileWatcher` with callbacks and inode-aware move detection
- Network diagnostics, latency and port checks
- Cross-platform process discovery and control
- Disk/root/filesystem discovery
- Expanded storage calculations
- Atomic integrity manifests
- Virtual filesystem with snapshots, transactions, import/export, search, hashing, and tree support
- Typed-package marker (`py.typed`)
- Expanded regression coverage in `tests/`

## Quick start

```python
from alera import Alera

with Alera("") as alera:
    alera.files.create_folder("documents")
    alera.files.create_file("documents/hello.txt", "Hello from Alera!")
    print(alera.files.read_file("documents/hello.txt"))
    print(alera.search.name("hello"))
    print(alera.inspector.inspect("documents/hello.txt"))
    print(alera.analytics.report())
    print(alera.diagnostics(deep=True))
```

## Runtime

Every Alera instance has a runtime controller:

```python
alera.runtime.capabilities()
alera.runtime.resources()
alera.runtime.diagnostics(deep=True)
alera.runtime.check_services()
alera.runtime.benchmark("files", "exists", "documents/hello.txt")
alera.runtime.gc_collect()
alera.close()
```

## Universal service power

Alera preserves each service's specialized API while giving public classes a common introspection layer:

```python
alera.files.capabilities()
alera.files.describe()
alera.files.health()
alera.files.snapshot()
alera.files.timed("exists", "hello.txt")
alera.files.safe(alera.files.read_file, "hello.txt", default="")
```

## Core services

`Alera` exposes dedicated services instead of forcing every feature into one giant class:

- Filesystem: `FileExplorer`, `PathTools`, `DirectoryTools`, `FileUtilities`, `VirtualFileSystem`
- Search/analysis: `SearchEngine`, `FileAnalysis`, `FileInspector`, `FilesystemAnalytics`, `StorageAnalyzer`
- Safety/recovery: recycle bin, `BackupManager`, `RecoveryManager`, `SnapshotManager`, `VersionManager`, `IntegrityManager`, `FileTransaction`
- Storage: `DiskManager`, `MountManager`, `StorageCalculator`, `TemporaryFiles`
- Security: `FileSecurity`, `EncryptionManager`, `PermissionTools`
- Runtime/system: `AleraRuntime`, `ProcessManager`, `NetworkManager`, `HealthChecker`, Android storage helpers
- Performance/IO: `AtomicFiles`, `FileCache`, `StreamTools`, `FileLock`, `FileWatcher`
- Data/indexing: `FileDatabase`, `SearchIndex`
- Archives/binary: `ArchiveManager`, `BinaryFileManager`
- Hidden/experimental: `HiddenFiles`, `HiddenFileExplorer`, `Experimental`, `HiddenConfig`

## Hidden storage

The experimental hidden-storage configuration defaults to Alera's own internal storage:

```python
alera.hidden_config.enabled = True
alera.hidden_config.storage = "internal"
alera.hidden_config.save()
```

Android shared storage can be selected explicitly:

```python
alera.hidden_config.storage = "android"
alera.hidden_config.save()
```

Hidden storage can also be disabled:

```python
alera.hidden_config.enabled = False
alera.hidden_config.save()
```

## Deletion model

`FileExplorer.delete()` and `deletes()` move items into Alera's recycle bin. `perm_delete()` and `perm_deletes()` permanently delete normal filesystem items. Bin-specific deletion remains explicit through `bin_delete()`, `spef_delete()`, and `clear_bin()`.

Cleanup is also opt-in: every `CleanupManager` category starts disabled. Use `preview()` or `clean(dry_run=True)` before enabling destructive categories.

## Requirements

Python 3.10+.

## License

MIT
