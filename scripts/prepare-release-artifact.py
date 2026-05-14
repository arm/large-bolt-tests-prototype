#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict


REQUIRED_METADATA_FIELDS = [
    "archive_filename",
    "asset_sha256",
    "binary_path",
    "checksum_filename",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a release-backed artifact from artifact.json, verify the "
            "packaged archive, extract it into a cache directory, and print the "
            "binary path."
        )
    )
    parser.add_argument(
        "--artifact-metadata",
        help="Path to artifact.json. Mutually exclusive with --release-root.",
    )
    parser.add_argument(
        "--release-root",
        help=(
            "Root directory containing releases/ for "
            "large-bolt-tests-prototype artifacts."
        ),
    )
    parser.add_argument("--name", help="Artifact name, for example bzip2.")
    parser.add_argument("--version", help="Artifact version, for example 1.0.8.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the release archive should be extracted.",
    )
    return parser.parse_args()


def resolve_metadata_path(args: argparse.Namespace) -> Path:
    if args.artifact_metadata:
        if args.release_root or args.name or args.version:
            raise ValueError(
                "--artifact-metadata cannot be combined with --release-root, "
                "--name, or --version"
            )
        return Path(args.artifact_metadata)

    missing = [
        flag
        for flag, value in (
            ("--release-root", args.release_root),
            ("--name", args.name),
            ("--version", args.version),
        )
        if not value
    ]
    if missing:
        missing_csv = ", ".join(missing)
        raise ValueError(
            "either --artifact-metadata or all of --release-root, --name, "
            f"and --version are required (missing {missing_csv})"
        )

    return (
        Path(args.release_root)
        / "releases"
        / "binary"
        / args.name
        / f"v{args.version}"
        / "artifact.json"
    )


def load_metadata(metadata_path: Path) -> Dict[str, Any]:
    with metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)

    missing = [field for field in REQUIRED_METADATA_FIELDS if field not in metadata]
    if missing:
        missing_csv = ", ".join(sorted(missing))
        raise ValueError(f"artifact metadata is missing required fields: {missing_csv}")

    return metadata


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_checksum_file(checksum_path: Path, archive_filename: str) -> str:
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split(None, 1)
        if len(parts) != 2:
            continue

        checksum_value, filename = parts
        if filename.strip().lstrip("*") == archive_filename:
            return checksum_value

    raise ValueError(
        f"checksum file does not contain an entry for archive {archive_filename}"
    )


def extract_archive(archive_path: Path, output_dir: Path) -> None:
    tar_path = shutil.which("tar")
    if tar_path is None:
        raise FileNotFoundError("required tool not found on PATH: tar")

    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [tar_path, "--zstd", "-xf", str(archive_path), "-C", str(output_dir)],
        check=True,
        text=True,
        capture_output=True,
    )


def main() -> int:
    args = parse_args()

    try:
        metadata_path = resolve_metadata_path(args)
        output_dir = Path(args.output_dir)

        if not metadata_path.is_file():
            raise FileNotFoundError(f"artifact metadata does not exist: {metadata_path}")

        metadata = load_metadata(metadata_path)
        release_dir = metadata_path.parent
        archive_path = release_dir / metadata["archive_filename"]
        checksum_path = release_dir / metadata["checksum_filename"]
        binary_path = output_dir / metadata["binary_path"]

        if not archive_path.is_file():
            raise FileNotFoundError(f"release archive does not exist: {archive_path}")
        if not checksum_path.is_file():
            raise FileNotFoundError(f"checksum file does not exist: {checksum_path}")

        checksum_from_file = load_checksum_file(
            checksum_path, metadata["archive_filename"]
        )
        if checksum_from_file != metadata["asset_sha256"]:
            raise ValueError(
                "artifact metadata checksum does not match SHA256SUMS entry: "
                f"{metadata['asset_sha256']} != {checksum_from_file}"
            )

        archive_sha256 = compute_sha256(archive_path)
        if archive_sha256 != metadata["asset_sha256"]:
            raise ValueError(
                f"archive checksum mismatch: expected {metadata['asset_sha256']}, "
                f"got {archive_sha256}"
            )

        if not binary_path.is_file():
            extract_archive(archive_path, output_dir)

        if not binary_path.is_file():
            raise FileNotFoundError(
                f"expected binary was not found after extraction: {binary_path}"
            )
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(binary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
