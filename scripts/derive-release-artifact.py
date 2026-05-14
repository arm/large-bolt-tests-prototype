#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys


REQUIRED_FIELDS = [
    "name",
    "platform",
    "version",
    "recipe",
    "source_url",
    "source_sha256",
    "binary_path",
    "test",
    "justification",
]


def default_artifact_root() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    repo_token = repo_root.name.replace(" ", "-")
    return Path.home() / f"{repo_token}-artifacts"


def load_manifest(manifest_path: Path) -> dict:
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        missing_csv = ", ".join(sorted(missing))
        raise ValueError(f"manifest is missing required fields: {missing_csv}")

    return data


def derive_release_data(manifest: dict, manifest_path: Path, artifact_root: Path) -> dict:
    name = manifest["name"]
    platform = manifest["platform"]
    version = manifest["version"]
    platform_token = platform.replace("/", "-")
    asset_basename = f"{name}-{platform_token}-v{version}"
    archive_filename = f"{asset_basename}.tar.zst"
    checksum_filename = "SHA256SUMS"
    metadata_filename = "artifact.json"
    release_tag = f"binary/{name}/v{version}"
    release_name = f"{name} {platform} v{version}"
    staging_dir_name = asset_basename
    local_release_dir = artifact_root / "releases" / release_tag
    local_work_dir = artifact_root / "work" / asset_basename
    local_derived_path = artifact_root / "derived" / f"{asset_basename}.json"

    return {
        "manifest_path": manifest_path.as_posix(),
        "name": name,
        "platform": platform,
        "platform_token": platform_token,
        "version": version,
        "recipe_path": manifest["recipe"],
        "source_url": manifest["source_url"],
        "source_sha256": manifest["source_sha256"],
        "binary_path": manifest["binary_path"],
        "test_path": manifest["test"],
        "justification": manifest["justification"],
        "asset_basename": asset_basename,
        "archive_filename": archive_filename,
        "checksum_filename": checksum_filename,
        "metadata_filename": metadata_filename,
        "release_tag": release_tag,
        "release_name": release_name,
        "staging_dir_name": staging_dir_name,
        "local_artifact_root": artifact_root.as_posix(),
        "local_release_dir": local_release_dir.as_posix(),
        "local_work_dir": local_work_dir.as_posix(),
        "local_derived_path": local_derived_path.as_posix(),
        "local_archive_path": (local_release_dir / archive_filename).as_posix(),
        "local_checksum_path": (local_release_dir / checksum_filename).as_posix(),
        "local_metadata_path": (local_release_dir / metadata_filename).as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derive release artifact naming and paths from a recipe manifest."
    )
    parser.add_argument("manifest", help="Path to the recipe manifest JSON file.")
    parser.add_argument(
        "--artifact-root",
        default=str(default_artifact_root()),
        help="Root directory for local work and release output paths.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    artifact_root = Path(args.artifact_root)

    try:
        manifest = load_manifest(manifest_path)
        derived = derive_release_data(manifest, manifest_path, artifact_root)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    json.dump(derived, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
