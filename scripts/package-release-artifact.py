#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional


REQUIRED_FIELDS = [
    "name",
    "platform",
    "platform_token",
    "version",
    "recipe_path",
    "binary_path",
    "asset_basename",
    "archive_filename",
    "checksum_filename",
    "metadata_filename",
    "release_tag",
    "release_name",
    "local_artifact_root",
    "local_release_dir",
    "local_work_dir",
    "local_archive_path",
    "local_checksum_path",
    "local_metadata_path",
]

CONTAINER_RUNTIME_PATHS = [
    ".dockerenv",
    "dev",
    "etc/hostname",
    "etc/hosts",
    "etc/resolv.conf",
    "proc",
    "sys",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build, extract, and package a release artifact from derived recipe JSON."
    )
    parser.add_argument(
        "derived_json",
        help="Path to derived JSON from derive-release-artifact.py, or '-' for stdin.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned commands and paths without invoking Docker or tar.",
    )
    parser.add_argument(
        "--container-tool",
        default="docker",
        help="Container CLI to use for build/create/export operations.",
    )
    return parser.parse_args()


def load_derived_json(path_arg: str) -> Dict[str, Any]:
    if path_arg == "-":
        return json.load(sys.stdin)

    with Path(path_arg).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_derived_json(data: Dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        missing_csv = ", ".join(sorted(missing))
        raise ValueError(f"derived JSON is missing required fields: {missing_csv}")


def sanitize_image_namespace(token: str) -> str:
    sanitized = re.sub(r"[^a-z0-9._-]+", "-", token.lower()).strip("-.")
    return sanitized or "artifact"


def sanitize_image_tag(name: str, version: str, platform_token: str) -> str:
    repo_root = Path(__file__).resolve().parent.parent
    namespace = sanitize_image_namespace(f"{repo_root.name}-local")
    return f"{namespace}/{name}:v{version}-{platform_token}"


def run_command(
    cmd: List[str], dry_run: bool
) -> Optional[subprocess.CompletedProcess]:
    if dry_run:
        print("$ " + " ".join(cmd))
        return None

    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def require_tool(tool: str) -> None:
    if shutil.which(tool) is None:
        raise FileNotFoundError(
            f"required tool not found on PATH: {tool}. "
            f"Install it or rerun with --container-tool pointing to an available CLI."
        )


def write_json(path: Path, payload: Dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        print(f"would write JSON: {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def write_text(path: Path, contents: str, dry_run: bool) -> None:
    if dry_run:
        print(f"would write text: {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def prune_runtime_artifacts(rootfs_dir: Path, dry_run: bool) -> None:
    for relative_path in CONTAINER_RUNTIME_PATHS:
        path = rootfs_dir / relative_path
        if dry_run:
            print(f"would remove runtime artifact: {path}")
            continue

        if not path.exists():
            continue

        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent

    try:
        derived = load_derived_json(args.derived_json)
        validate_derived_json(derived)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        require_tool(args.container_tool)
        require_tool("tar")
        require_tool("sha256sum")
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    recipe_path = repo_root / derived["recipe_path"]
    release_dir = Path(derived["local_release_dir"])
    work_dir = Path(derived["local_work_dir"])
    rootfs_dir = work_dir / "rootfs"
    export_tar = work_dir / "rootfs.tar"
    archive_path = Path(derived["local_archive_path"])
    checksum_path = Path(derived["local_checksum_path"])
    metadata_path = Path(derived["local_metadata_path"])
    binary_path = rootfs_dir / derived["binary_path"]
    image_tag = sanitize_image_tag(
        derived["name"], derived["version"], derived["platform_token"]
    )

    if not recipe_path.is_file():
        print(f"error: recipe does not exist: {recipe_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"repo_root={repo_root}")
        print(f"recipe_path={recipe_path}")
        print(f"work_dir={work_dir}")
        print(f"release_dir={release_dir}")
        print(f"archive_path={archive_path}")

    if work_dir.exists() and not args.dry_run:
        shutil.rmtree(work_dir)
    if release_dir.exists() and not args.dry_run:
        shutil.rmtree(release_dir)

    if not args.dry_run:
        work_dir.mkdir(parents=True, exist_ok=True)
        rootfs_dir.mkdir(parents=True, exist_ok=True)
        release_dir.mkdir(parents=True, exist_ok=True)

    build_cmd = [
        args.container_tool,
        "buildx",
        "build",
        "--load",
        "--platform",
        derived["platform"],
        "--build-arg",
        f"TARGETPLATFORM={derived['platform']}",
        "--file",
        str(recipe_path),
        "--tag",
        image_tag,
        str(repo_root),
    ]

    container_id = None
    try:
        run_command(build_cmd, args.dry_run)

        # Scratch-based artifact images have no default command; provide a
        # placeholder because we only need a container filesystem for export.
        create_cmd = [
            args.container_tool,
            "create",
            image_tag,
            "/__large_bolt_tests_export__",
        ]
        create_result = run_command(create_cmd, args.dry_run)
        if create_result is not None:
            container_id = create_result.stdout.strip()

        export_cmd = [
            args.container_tool,
            "export",
            container_id or "<container-id>",
            "--output",
            str(export_tar),
        ]
        run_command(export_cmd, args.dry_run)

        extract_cmd = ["tar", "-xf", str(export_tar), "-C", str(rootfs_dir)]
        run_command(extract_cmd, args.dry_run)
        prune_runtime_artifacts(rootfs_dir, args.dry_run)

        if not args.dry_run and not binary_path.is_file():
            print(
                f"error: expected binary was not found after extraction: {binary_path}",
                file=sys.stderr,
            )
            return 1

        archive_cmd = [
            "tar",
            "--zstd",
            "-cf",
            str(archive_path),
            "-C",
            str(rootfs_dir),
            ".",
        ]
        run_command(archive_cmd, args.dry_run)

        sha_cmd = ["sha256sum", str(archive_path)]
        sha_result = run_command(sha_cmd, args.dry_run)
        asset_sha256 = "<sha256>"
        if sha_result is not None:
            asset_sha256 = sha_result.stdout.split()[0]

        checksum_contents = f"{asset_sha256}  {archive_path.name}\n"
        write_text(checksum_path, checksum_contents, args.dry_run)

        metadata = dict(derived)
        metadata["asset_sha256"] = asset_sha256
        metadata["archive_path"] = archive_path.as_posix()
        write_json(metadata_path, metadata, args.dry_run)
    except subprocess.CalledProcessError as error:
        print(error.stderr, file=sys.stderr, end="")
        return error.returncode
    finally:
        if container_id is not None:
            rm_cmd = [args.container_tool, "rm", "-f", container_id]
            try:
                run_command(rm_cmd, False)
            except subprocess.CalledProcessError:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
