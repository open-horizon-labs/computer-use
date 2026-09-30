# Changelog

Versions follow Cua Driver minor releases (0.31 targets Cua Driver 0.31).

## 0.31.0 (unreleased, integration/0.31)

### Breaking / behavior changes
- `close_tab` presses the tab's own Close button in the tab strip (AX, background, no fronting, no `allow_foreground`); zero or several matching tabs refuse `tab_close_control_not_found` / `tab_close_control_ambiguous` before any press. Cmd+W (foreground) remains only as an explicit `allow_foreground: true` fallback when the strip shows no such control (#4).

### Added
- `goto {url, expect}` plan step: navigates the window's active tab in the user's own browser profile and is done only when the tab reports the requested page; typed stops `navigated_elsewhere`, `login_wall`, `landing_unknown`, `browser_tab_ambiguous` (CE-FACADE-007, #28).
- `open_tab {url, expect}` and `close_tab` plan steps; `close_tab` closes only the tab this facade opened (CE-FACADE-007, #28).
- A Driver refusal to attach to the browser profile is `permission_required` naming `--grant existing-profile`; the facade never switches to another browser or profile (#28).

### Removed
- The unqualified Qwen chat-completion vision fallback in `workers/visual_worker.py`: without `CUA_SYSTEMONE_URL` the visual provider is unavailable, nothing is sent, verification ends unverified and visual choose defers (#8).

### Fixed
- A Driver daemon restart no longer leaves the facade with a dead session: a read-only Driver call that fails as if the session were gone re-runs `start_session` once and is retried once (`driver_session_restarted` in the trace); a mutating call is never retried, and a failed call reports only tool, exit class and whether a restart was tried (#31).
- A Driver answer with `effect: "refused"` (top level or on any action) is a refusal with the Driver's code, never `delivered` (#38).
- `cua_look` counts only the page, not the browser's menu bar, on windows without a web area: native windows keep the AXWindow subtree minus the menu bar, title-bar buttons and off-window elements (toolbars stay), so a drawn canvas such as an Android emulator reaches Perception (#27).

### Known issues
- Tested live against a local source build of Cua Driver 0.31.0; the signed 0.31.0 release was not yet published.
