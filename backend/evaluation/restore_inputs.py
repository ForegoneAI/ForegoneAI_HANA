"""Restore only checksum-verified input snapshots for the benchmark.

Source PDFs/workbooks are not committed (see .gitignore). Three ways to get
them back, which can be combined:

    # the supplied pack
    python -m backend.evaluation.restore_inputs --archive /path/to/HANA_M1_Benchmark_Pack.zip
    # a folder holding the original files under any names (e.g. a Drive download)
    python -m backend.evaluation.restore_inputs --source-dir /path/to/deal/files
    # the public broker offering memoranda listed with a URL in the manifest
    python -m backend.evaluation.restore_inputs --download-public

No code or answer keys from an archive or folder are executed or overwritten.
Files are matched by SHA-256 against the versioned manifest, and written only
to the manifest's own paths, never to a location an archive names.
"""

import argparse
import hashlib
import urllib.request
import zipfile
from pathlib import Path

from backend.evaluation.dataset import DEFAULT_ROOT, Dataset, load_dataset, sha256

MAX_SOURCE_BYTES = 50 * 1024 * 1024


def _write(dataset: Dataset, did: str, content: bytes) -> None:
    doc = dataset.documents[did]
    if hashlib.sha256(content).hexdigest() != doc["sha256"]:
        raise ValueError(f"Source checksum mismatch: {did}")
    target = dataset.root / doc["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(target)


def missing_documents(dataset: Dataset) -> list[str]:
    """Documents that are absent or don't match their manifest checksum."""
    missing = []
    for did, doc in dataset.documents.items():
        path = dataset.root / doc["path"]
        if not path.is_file() or sha256(path) != doc["sha256"]:
            missing.append(did)
    return sorted(missing)


def restore(archive: Path, root: Path) -> None:
    dataset = load_dataset(root)
    sources = {}
    with zipfile.ZipFile(archive) as pack:
        for did, doc in dataset.documents.items():
            member = "hana-benchmark/" + doc["path"]
            info = pack.getinfo(member)
            if info.file_size > MAX_SOURCE_BYTES:
                raise ValueError(f"Oversized source: {did}")
            content = pack.read(member)
            if hashlib.sha256(content).hexdigest() != doc["sha256"]:
                raise ValueError(f"Source checksum mismatch: {did}")
            sources[did] = content
    # Verify the complete archive before changing any local input.
    for did, content in sources.items():
        _write(dataset, did, content)


def restore_from_directory(source_dir: Path, root: Path) -> list[str]:
    """Copy every file under `source_dir` whose SHA-256 matches a manifest
    document; filenames don't matter. Returns the document IDs restored.
    Two manifest entries with the same content (duplicate uploads) are both
    restored from one file."""
    dataset = load_dataset(root)
    wanted: dict[str, list[str]] = {}
    for did, doc in dataset.documents.items():
        wanted.setdefault(doc["sha256"], []).append(did)
    restored = []
    for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
        if path.stat().st_size > MAX_SOURCE_BYTES or path.resolve().is_relative_to(dataset.root):
            continue
        digest = sha256(path)
        for did in wanted.pop(digest, []):
            _write(dataset, did, path.read_bytes())
            restored.append(did)
    return sorted(restored)


def download_public(root: Path, *, opener=urllib.request.urlopen, timeout: float = 60) -> tuple[list[str], dict[str, str]]:
    """Fetch manifest documents that carry a public `url`. A download whose
    checksum differs (the broker replaced the file) is rejected, because the
    labels were written against the snapshot. Returns (restored, failures)."""
    dataset = load_dataset(root)
    restored, failures = [], {}
    for did in missing_documents(dataset):
        url = dataset.documents[did].get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "H9N-benchmark-restore"})
            with opener(request, timeout=timeout) as response:
                content = response.read(MAX_SOURCE_BYTES + 1)
            if len(content) > MAX_SOURCE_BYTES:
                raise ValueError("oversized download")
            _write(dataset, did, content)
            restored.append(did)
        except Exception as exc:  # one unreachable broker site shouldn't stop the rest
            failures[did] = f"{type(exc).__name__}: {exc}"
    return restored, failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, help="HANA_M1_Benchmark_Pack.zip")
    parser.add_argument("--source-dir", type=Path, help="Folder containing original source files under any names")
    parser.add_argument("--download-public", action="store_true", help="Download manifest documents that have a public URL")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    if not (args.archive or args.source_dir or args.download_public):
        parser.error("Give --archive, --source-dir, and/or --download-public.")
    failures = {}
    try:
        if args.archive:
            restore(args.archive, args.dataset)
        if args.source_dir:
            if not args.source_dir.is_dir():
                raise ValueError(f"Not a directory: {args.source_dir}")
            restore_from_directory(args.source_dir, args.dataset)
        if args.download_public:
            _, failures = download_public(args.dataset)
        still_missing = missing_documents(load_dataset(args.dataset))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    for did, reason in failures.items():
        print(f"Download failed for {did}: {reason}")
    print("All benchmark inputs restored and checksum-verified." if not still_missing
          else "Checksum-verified inputs restored. Still missing: " + ", ".join(still_missing))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
