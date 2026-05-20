# large-bolt-tests-prototype

`large-bolt-tests-prototype` is a BOLT regression suite used as an
external LLVM project.

## Current Repository Status

This checkout is in a transition state:

- All active coverage in this tree targets
  AArch64.
- The new local release-artifact workflow is implemented for the `bzip2` test.
- `bzip2` is currently the reference example for the release-backed model:
  recipe -> packaged local release -> lit test consumption.

The key files for the current release backed flow are:

- `scripts/derive-release-artifact.py`
- `scripts/package-release-artifact.py`
- `scripts/prepare-release-artifact.py`
- `test/AArch64/Recipes/bzip2-aarch64.recipe.json`
- `test/AArch64/Recipes/bzip2-aarch64.Dockerfile`
- `test/AArch64/bzip2.test`

## What The Scripts Do

### `derive-release-artifact.py`

Reads a recipe manifest and derives the local naming and directory layout for a
release artifact tree.

### `package-release-artifact.py`

Builds the recipe container image, exports its filesystem, strips container
runtime artifacts, archives the result as a `.tar.zst`, writes `SHA256SUMS`,
and writes `artifact.json`.

### `prepare-release-artifact.py`

Used by lit tests. It reads `artifact.json`, verifies the archive checksum,
extracts the archive into a caller-provided directory, and prints the resolved
binary path.

## Prerequisites

### For the release-artifact scripts

- `python3`
- `docker` with `buildx`
- `tar` with `--zstd` support
- `sha256sum`
- `zstd`

The current `bzip2` recipe builds `linux/arm64`. On a non-AArch64 host, Docker
must already be set up to build that platform.

### For running the test with LLVM/BOLT

Configure LLVM with this repository as an external project and build BOLT tools
normally. Example:

```bash
git clone https://github.com/llvm/llvm-project
git clone <repository-url> large-bolt-tests-prototype

cmake -G Ninja \
  -S llvm-project/llvm \
  -B bolt-build \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_TARGETS_TO_BUILD="AArch64" \
  -DLLVM_ENABLE_PROJECTS="clang;lld;bolt" \
  -DLLVM_EXTERNAL_PROJECTS="bolttests" \
  -DLLVM_EXTERNAL_BOLTTESTS_ARM_SOURCE_DIR="$PWD/large-bolt-tests-prototype"
```

When configured this way, LLVM adds the `check-large-bolt` lit target.

## Build A Local `bzip2` Release

Choose a local artifact root. The examples below use:

```bash
ARTIFACT_ROOT=/tmp/large-bolt-tests-prototype-artifacts
```

### 1. Derive the release layout

```bash
mkdir -p "$ARTIFACT_ROOT/derived"

python3 scripts/derive-release-artifact.py \
  test/AArch64/Recipes/bzip2-aarch64.recipe.json \
  --artifact-root "$ARTIFACT_ROOT" \
  > "$ARTIFACT_ROOT/derived/bzip2-linux-arm64-v1.0.8.json"
```

### 2. Build and package the local release

```bash
python3 scripts/package-release-artifact.py \
  "$ARTIFACT_ROOT/derived/bzip2-linux-arm64-v1.0.8.json"
```

This creates a local release tree under:

```text
$ARTIFACT_ROOT/releases/binary/bzip2/v1.0.8/
```

The release directory should contain:

- `bzip2-linux-arm64-v1.0.8.tar.zst`
- `SHA256SUMS`
- `artifact.json`

The packaging script also uses:

```text
$ARTIFACT_ROOT/work/bzip2-linux-arm64-v1.0.8/
```

as a temporary local work area.

### 3. Optional sanity check

You can validate the fetch-and-extract side directly before running lit:

```bash
python3 scripts/prepare-release-artifact.py \
  --release-root "$ARTIFACT_ROOT" \
  --name bzip2 \
  --version 1.0.8 \
  --output-dir "$ARTIFACT_ROOT/test-cache/bzip2"
```

If successful, the command prints the extracted binary path, which should be:

```text
$ARTIFACT_ROOT/test-cache/bzip2/bin/bzip2
```

## Run The `bzip2` Test

After configuring LLVM as shown above, build your LLVM tree so `llvm-bolt` is
available in the build you want to test. Then run the `bzip2` test explicitly
and point lit at the local release root:

```bash
llvm-lit \
  --param=release_root="$ARTIFACT_ROOT" \
  --filter='bzip2\.test$' \
  "$PWD/bolt-build/tools/bolttests" \
  -a
```

You can also provide the release root through the environment instead of a lit
parameter:

```bash
export LARGE_BOLT_TESTS_PROTOTYPE_RELEASE_ROOT="$ARTIFACT_ROOT"
```

`LARGE_BOLT_RELEASE_ROOT` is still accepted as a backward-compatible alias.

If you prefer the generated LLVM target, running `check-large-bolt`
from the `bolt-built` directory is still the suite entry point for
this external project. For example:
```bash
$PWD/bolt-built ninja check-large-bolt
```

For the current local release-backed `bzip2`
workflow, running `llvm-lit` directly with `--param=release_root=...`
is the clearest option. For example:
```bash
llvm-lit --param=release_root=$ARTIFACT_ROOT --filter='bzip2\.test$' $PWD/bolt-built/tools/bolttests -a
```

The `bzip2` test uses that release root to locate:

```text
releases/binary/bzip2/v1.0.8/artifact.json
```

and then calls `prepare-release-artifact.py` to verify and extract the archive
before invoking `llvm-bolt` on the resolved `bin/bzip2`.

## Notes For Adding More Release-Backed Tests

The current `bzip2` files are the template for additional release-backed
artifacts:

1. Add a recipe manifest JSON under `test/AArch64/Recipes/`.
2. Add the matching Dockerfile recipe.
3. Use `derive-release-artifact.py` and `package-release-artifact.py` to produce
   a local release tree.
4. Write the lit test so it resolves the binary through
   `prepare-release-artifact.py`.
