# Alera

A powerful, cross-platform Python filesystem and system-information toolkit.

Alera is designed to make file management feel like a real file explorer while keeping the API simple, typed, safe, and Pythonic.

## 0.2.0 highlights

- Unified `Alera(...)` service hub
- Advanced `SearchEngine` with metadata, content, hash, MIME, size, and duplicate searches
- Configurable, opt-in `CleanupManager` with preview/dry-run and exclusions
- Verified `BackupManager` with nested-destination protection and restore verification
- Numbered `VersionManager` snapshots with checksums and atomic manifests
- SQLite `FileDatabase` index with incremental refresh and duplicate lookup
- `FileInspector` with file signatures, encoding detection, entropy, MIME data, and streaming text statistics
- Improved filesystem analytics and storage analysis
- Improved polling `FileWatcher` with callbacks and inode-aware move detection
- Network diagnostics, latency and port checks
- Cross-platform process discovery and control
- Disk/root/filesystem discovery
- Expanded storage calculations
- Atomic integrity manifests
- Typed-package marker (`py.typed`)
- Expanded regression coverage in `tests/`

## Quick start

```python
from alera import Alera

alera = Alera("")

alera.files.create_folder("documents")
alera.files.create_file("documents/hello.txt", "Hello from Alera!")
print(alera.files.read_file("documents/hello.txt"))

print(alera.search.name("hello"))
print(alera.inspector.inspect("documents/hello.txt"))
print(alera.analytics.report())
print(alera.health.health())
```

## Core services

`Alera` exposes dedicated services instead of forcing every feature into one giant class:

- Filesystem: `FileExplorer`, `PathTools`, `DirectoryTools`, `FileUtilities`, `VirtualFileSystem`
- Search/analysis: `SearchEngine`, `FileAnalysis`, `FileInspector`, `FilesystemAnalytics`, `StorageAnalyzer`
- Safety/recovery: recycle bin, `BackupManager`, `RecoveryManager`, `SnapshotManager`, `VersionManager`, `IntegrityManager`, `FileTransaction`
- Storage: `DiskManager`, `MountManager`, `StorageCalculator`, `TemporaryFiles`
- Security: `FileSecurity`, `EncryptionManager`, `PermissionTools`
- Runtime/system: `ProcessManager`, `NetworkManager`, `HealthChecker`, Android storage helpers
- Performance/IO: `AtomicFiles`, `FileCache`, `StreamTools`, `FileLock`, `FileWatcher`
- Data/indexing: `FileDatabase`

## Deletion model

`FileExplorer.delete()` and `deletes()` move items into Alera's recycle bin. `perm_delete()` and `perm_deletes()` permanently delete normal filesystem items. Bin-specific deletion remains explicit through `bin_delete()`, `spef_delete()`, and `clear_bin()`.

Cleanup is also opt-in: every `CleanupManager` category starts disabled. Use `preview()` or `clean(dry_run=True)` before enabling destructive categories.

## Requirements

Python 3.10+.

## License

MIT
