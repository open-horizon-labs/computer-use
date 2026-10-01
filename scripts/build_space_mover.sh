#!/bin/sh
# Build the space-mover helper (issue #60): single-file Swift, no Xcode project, no dependencies.
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/computer_use/spaces/bin"
mkdir -p "$out"
xcrun swiftc -O -swift-version 5 "$root/computer_use/spaces/space-mover.swift" -o "$out/space-mover"
echo "$out/space-mover"
