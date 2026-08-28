#!/usr/bin/env bash
# Builds the Expedient Employment macOS / Linux release artifacts.
#
#   ./packaging/build-posix.sh          # auto-detect host platform
#   ./packaging/build-posix.sh mac      # macOS targets (dmg, zip)  — must run on macOS
#   ./packaging/build-posix.sh linux    # Linux targets (AppImage)  — must run on Linux
#
# Steps:
#   1. Build the GUI (npm run build in gui/).
#   2. Run electron-builder for the selected platform targets.
#
# Artifacts land in release/ at the repository root.
# Nothing is installed globally; electron-builder runs through npx.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUI_DIR="$REPO_ROOT/gui"
RELEASE_DIR="$REPO_ROOT/release"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  case "$(uname -s)" in
    Darwin) TARGET="mac" ;;
    Linux)  TARGET="linux" ;;
    *) echo "Unknown host platform '$(uname -s)'. Pass 'mac' or 'linux' explicitly." >&2; exit 1 ;;
  esac
fi

if [ "$TARGET" = "mac" ] && [ "$(uname -s)" != "Darwin" ]; then
  echo "macOS installers (dmg/zip) can only be built on macOS." >&2
  exit 1
fi
if [ "$TARGET" = "linux" ] && [ "$(uname -s)" != "Linux" ]; then
  echo "Linux AppImage builds must run on Linux." >&2
  exit 1
fi

VERSION="$(node -p "require('$GUI_DIR/package.json').version" 2>/dev/null || true)"
if [ -z "$VERSION" ]; then
  echo "Could not read the version from gui/package.json (is Node.js installed?)." >&2
  exit 1
fi
echo "Building Expedient Employment $VERSION for $TARGET"

cd "$GUI_DIR"
if [ ! -d node_modules ]; then
  echo "Installing GUI dependencies (npm install)..."
  npm install
fi

echo "Building the GUI (npm run build)..."
npm run build

echo "Running electron-builder (--$TARGET)..."
npx --yes electron-builder --config electron-builder.yml "--$TARGET"

mkdir -p "$RELEASE_DIR"
shopt -s nullglob
for artifact in "$GUI_DIR"/release/*.AppImage "$GUI_DIR"/release/*.dmg "$GUI_DIR"/release/*.zip; do
  cp -f "$artifact" "$RELEASE_DIR/"
  echo "Artifact: $RELEASE_DIR/$(basename "$artifact")"
done

echo
echo "$TARGET release complete. Artifacts are in: $RELEASE_DIR"
