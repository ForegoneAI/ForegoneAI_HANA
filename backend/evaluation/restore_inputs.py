"""Restore only checksum-verified input snapshots from the supplied ZIP.

No code or answer keys from the archive are executed or overwritten. Paths
come from the versioned manifest, not from ZIP extraction destinations.
"""

import argparse
import hashlib
import zipfile
from pathlib import Path

from backend.evaluation.dataset import DEFAULT_ROOT, load_dataset


def restore(archive: Path, root: Path) -> None:
    dataset = load_dataset(root)
    sources = {}
    with zipfile.ZipFile(archive) as pack:
        for did, doc in dataset.documents.items():
            member = "hana-benchmark/" + doc["path"]
            info = pack.getinfo(member)
            if info.file_size > 50 * 1024 * 1024:
                raise ValueError(f"Oversized source: {did}")
            content = pack.read(member)
            if hashlib.sha256(content).hexdigest() != doc["sha256"]:
                raise ValueError(f"Source checksum mismatch: {did}")
            sources[doc["path"]] = content
    # Verify the complete archive before changing any local input.
    for name, content in sources.items():
        target = dataset.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    try:
        restore(args.archive, args.dataset)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print("Restored checksum-verified benchmark inputs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
