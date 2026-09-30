# Parking a window away from the user (space-mover, issue #60)

`computer_use/spaces/space-mover.swift` is a single-file Swift helper (no Xcode project, no dependencies). Build it with
`scripts/build_space_mover.sh` (output `computer_use/spaces/bin/space-mover`, gitignored); `computer_use/spaces_client.py`
builds it on demand and wraps it. It is not wired into look/do yet.

## Mechanisms

1. **Virtual display (primary).** `space-mover display serve` creates a headless 1920x1080 virtual display and blocks
   until SIGTERM; the display exists only while that process lives, so the client starts it as a child
   (`ensure_agent_display()`) and stops it on shutdown (`stop()`). `move --window-id W --display D` sets the window's
   Accessibility position inside that display (public `kAXPositionAttribute`, size kept unless larger than the display)
   and verifies the new CGWindowList bounds. Nothing is mirrored, so no Screen Recording permission.
2. **Mission Control drag (fallback, only when `fallback_space` is configured).** `move --window-id W --space N`
   ports the method of PaperWM.spoon PR #174 (MIT, notice in the source header): open Mission Control, find the
   window thumbnail by title (middle-ellipsis aware, refuses ambiguity) and the target desktop, post one synthetic drag
   sharing a single mouse event number, close Mission Control, and verify via the window's Space and on-screen state.

Other commands: `trusted [--prompt]`, `spaces`, `displays`. JSON on stdout. Exit codes: 0 ok, 1 move refused or not
verified (`moved:false`, `code`, `reason`), 2 usage, 3 not trusted for Accessibility, 4 unavailable. Success is never
reported without verification. Client errors: `space_mover_unavailable`, `space_mover_untrusted`, `window_not_moved`.

## Private API (marked in the source)

`display serve` uses the private CoreGraphics classes `CGVirtualDisplayDescriptor`, `CGVirtualDisplayMode`,
`CGVirtualDisplaySettings`, `CGVirtualDisplay` through the Objective-C runtime (no public headers; same approach as
DeskPad). Space listing and verification read `CGSCopyManagedDisplaySpaces` and `CGSCopySpacesForWindows`, and
`_AXUIElementGetWindow` maps an AX window to its CGWindowID; all read-only. Any of these can change between macOS
releases; the helper fails with a typed error rather than guessing.

## Grant

Moves need Accessibility for the helper. Check with `space-mover trusted`; it reports `true` when the launching app
(terminal, agent host) already has the grant, which is inherited. Otherwise add the exact binary path under System
Settings > Privacy & Security > Accessibility, or run `space-mover trusted --prompt`. `spaces`, `displays` and
`display serve` need no grant.

## Visible effects

- A virtual display adds a display to the desktop layout for as long as the helper runs (it can change which display is
  main and where windows land; stop the helper to restore the layout).
- A Mission Control fallback move shows Mission Control for about a second and moves the pointer; the pointer is
  restored afterwards.
