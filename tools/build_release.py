"""Create a clean distributable ZIP, excluding local environments and real data."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
destination = root.parent / "BrainFicial.zip"
with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(p in {".venv", "__pycache__", ".git", "real", "live"} or p.endswith(".egg-info") for p in relative.parts):
            continue
        if path.suffix.lower() in {".pyc", ".zip", ".mat"}:
            continue
        archive.write(path, Path("BrainFicial") / relative)
print(f"Created {destination.name} ({destination.stat().st_size:,} bytes)")
