# Alera

A powerful, cross-platform Python filesystem and system-information toolkit.

Alera is designed to make file management feel like a real file explorer while keeping the API simple, typed, safe, and Pythonic.

## Highlights

- `FileExplorer("")` or any base directory
- Text and **raw binary file support**
- Create files and folders
- Read, write, append, replace, rename, copy, and move
- `create_binary_file()` / `read_binary_file()` / `write_binary_file()` for bytes, bytearray, and memoryview
- Safe relative-path protection against escaping the explorer root
- Recycle-bin workflow instead of immediate deletion
- Restore one, many, or all deleted items
- Permanently delete normal files with `perm_delete()` / `perm_deletes()`
- Permanently remove bin entries with `bin_delete()` / `spef_delete()` / `clear_bin()`
- Recursive search and extension filtering
- Directory tree output
- File metadata and SHA/hash support
- Disk usage and free-space information
- CPU, RAM, GPU, storage, network, and Python runtime information
- No third-party runtime dependencies
- Best-effort cross-platform hardware reporting

## Quick start

```python
from alera import FileExplorer, spec_information

files = FileExplorer("")

# Text files
files.create_folder("documents")
files.create_file("documents/hello.txt", "Hello from Alera!")
print(files.read_file("documents/hello.txt"))

# Real binary files: bytes are preserved exactly, including 0x00 and 0xFF.
payload = bytes(range(256)) + b"\x00\xff"
files.create_binary_file("documents/data.bin", payload)
assert files.read_binary_file("documents/data.bin") == payload
files.write_binary_file("documents/data.bin", b"\x00\x01\xfe\xff")

# Explore
print(files.tree())
print(files.file_hash("documents/data.bin"))

# Safe deletion: the item goes to Alera's internal bin.
deleted = files.delete("documents/data.bin")
print(deleted)
print(files.list_bin())

# Restore it later.
files.restore(deleted.name)

# Permanent deletion is explicit.
files.perm_delete("documents/data.bin")

print(spec_information())
```

## Binary files

Binary operations use Python's binary file modes (`rb`, `wb`, and `xb`) and never decode the data as text. This makes them suitable for images, archives, executables, databases, compressed data, and arbitrary byte sequences.

```python
explorer.create_binary_file("image.dat", b"\x89PNG\r\n\x1a\n")
data = explorer.read_binary_file("image.dat")
explorer.write_binary_file("image.dat", data + b"extra")
```

`create_binary_file()` creates a new file and fails if it already exists. `write_binary_file()` replaces the file contents. Both accept `bytes`, `bytearray`, and `memoryview` and reject text strings so accidental encoding cannot silently corrupt binary data.

## API shape

```python
explorer = FileExplorer("/path/to/workspace")

explorer.create_folder("projects")
explorer.create_file("projects/readme.txt", "text")
explorer.create_binary_file("projects/data.bin", b"\x00\xff\x10")
explorer.write_file("projects/readme.txt", "new text")
explorer.write_binary_file("projects/data.bin", b"new binary data")
explorer.append_file("projects/readme.txt", "\nmore")
explorer.read_file("projects/readme.txt")
explorer.read_binary_file("projects/data.bin")
explorer.list_files("projects", recursive=True)
explorer.search("readme")
explorer.find_by_extension(".py")
explorer.tree()
explorer.metadata("projects/readme.txt")
explorer.file_hash("projects/data.bin")
explorer.delete("projects/data.bin")
```

## Deletion model

`delete()` and `deletes()` do **not** immediately destroy user files. They move items into `.alera_bin` so they can be restored. `perm_delete()` and `perm_deletes()` permanently delete normal filesystem items. `bin_delete()`, `spef_delete()`, and `clear_bin()` permanently remove items that are already in the recycle bin.

The internal `.alera_bin` directory is protected from normal filesystem operations and is excluded from normal listings, recursive searches, walks, and trees.

## Requirements

Python 3.9+.

## License

MIT
