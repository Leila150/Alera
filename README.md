# Alera

A powerful, cross-platform Python filesystem and system-information toolkit.

Alera is designed to make file management feel like a real file explorer while keeping the API simple, typed, and Pythonic.

## Highlights

- `FileExplorer("")` or any base directory
- Create files and folders
- Read, write, append, replace, rename, copy, and move
- Safe relative-path protection against escaping the explorer root
- Recycle-bin workflow instead of immediate deletion
- Restore one, many, or all deleted items
- Permanently clear selected bin entries
- Recursive search and extension filtering
- Directory tree output
- File metadata and hashes
- Disk usage and free-space information
- CPU, RAM, GPU, storage, network, and Python runtime information
- No third-party runtime dependencies
- Best-effort cross-platform hardware reporting

## Quick start

```python
from alera import FileExplorer, spec_information

files = FileExplorer("")
files.create_folder("documents")
files.create_file("documents/hello.txt", "Hello from Alera!")

print(files.read_file("documents/hello.txt"))
print(files.tree())
print(files.file_hash("documents/hello.txt"))

# Safe deletion: the item goes to Alera's internal bin.
files.delete("documents/hello.txt")
print(files.list_bin())

# Restore it later.
files.restore_bin()

print(spec_information())
```

## API shape

```python
explorer = FileExplorer("/path/to/workspace")

explorer.create_folder("projects")
explorer.create_file("projects/readme.txt", "text")
explorer.write_file("projects/readme.txt", "new text")
explorer.append_file("projects/readme.txt", "\nmore")
explorer.read_file("projects/readme.txt")
explorer.list_files("projects", recursive=True)
explorer.search("readme")
explorer.find_by_extension(".py")
explorer.tree()
explorer.metadata("projects/readme.txt")
explorer.file_hash("projects/readme.txt")
explorer.delete("projects/readme.txt")
```

## Deletion model

`delete()` and `deletes()` do not immediately destroy user files. They move them into `.alera_bin` so they can be restored. `bin_delete()`, `spef_delete()`, and `clear_bin()` are the permanent-deletion operations.

## Requirements

Python 3.9+.

## License

MIT
