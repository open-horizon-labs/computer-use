# Lightweight virtual display (issue #60)

This page describes OH's retained optional virtual-display browser, not Cua Spaces. For a separate guest desktop through Cua Spaces, see the skill's [Spaces guide](../skills/computer-use/references/spaces.md).

## Current runtime

The optional OH off_screen capability uses an owned Chromium profile on a verified virtual monitor. macOS treats it as another display, so the agent's browser can stay off the physical screen. The server constructs AgentDisplay(mode="required"); AgentDisplay constructs SpaceMover() without fallback_space. If the display cannot be created or the window cannot be placed and verified, the operation refuses. It does not move the window through Mission Control or fall back to the user's physical screen.

The helper is computer_use/spaces/space-mover.swift, built by scripts/build_space_mover.sh and wrapped by computer_use/spaces_client.py. display serve creates a headless virtual display as a child process; the display exists only while that process runs. move --display positions the exact window through Accessibility and verifies its CoreGraphics bounds. The owned browser is launched with placement seeded to the display's current bounds; a misplaced window is not accepted as isolated.

The current facade exposes only explicitly selected mobile and off_screen capabilities. It does not expose legacy user-profile/OBO or optional-display fallback settings. OBO uses native tools in the user's actual apps; see the [OBO guide](../skills/computer-use/references/obo.md). The adapter is disabled/unregistered by default; see [setup](../skills/computer-use/references/setup.md).

## Attribution and retained fallback

DeskPad's virtual-display approach informed the virtual monitor implementation. The helper uses private CoreGraphics display classes through the Objective-C runtime; this can break across macOS releases. Window positioning needs Accessibility; unavailable prerequisites return typed refusals. Locked-host operation has not been qualified.

The helper also retains a separate move --space command based on the Mission Control method in Michael Mogenson's PaperWM.spoon PR #174. Its MIT attribution remains in the source. SpaceMover.park can use it only when a caller explicitly supplies fallback_space. The current AgentDisplay/server path does not supply one, so this is retained code, not an active fallback or a current skill feature. Do not credit PaperWM as the mechanism behind the virtual monitor.

If called directly, that retained command briefly opens Mission Control and moves the pointer. The virtual-display route does not perform that drag. Creating a virtual monitor still changes macOS's display layout; isolation from the physical screen is not a guarantee of zero host-side effects.

## Evidence and limits

The virtual-display browser was qualified live on 2026-09-30 with Driver 0.31.0 and Chrome for Testing 154: the window opened on the virtual display, binding was exact and browser navigation worked. That bounded result does not establish locked-host support or comparative speed/token savings. The separate Cua Spaces qualification is in [its report](CUA-SPACES-QUALIFICATION-2026-10-02.md).

Historical configurable display modes, user-profile browser routing and Mission Control fallback policies are recoverable from Git history and codex/archive-general-facade-2026-10-02 at a531b43. They are not setup instructions for the current server.
