# Changelog

Versions follow Cua Driver minor releases (0.31 targets Cua Driver 0.31).

## 0.31.0 (unreleased, integration/0.31)

### Breaking / behavior changes
- `close_tab` requires the step's `allow_foreground: true` while it closes with Cmd+W (Chrome ignores a background Cmd+W). #4 replaces this with a background close.

### Added
- `goto {url, expect}` plan step: navigates the window's active tab in the user's own browser profile and is done only when the tab reports the requested page; typed stops `navigated_elsewhere`, `login_wall`, `landing_unknown`, `browser_tab_ambiguous` (CE-FACADE-007, #28).
- `open_tab {url, expect}` and `close_tab` plan steps; `close_tab` closes only the tab this facade opened (CE-FACADE-007, #28).
- A Driver refusal to attach to the browser profile is `permission_required` naming `--grant existing-profile`; the facade never switches to another browser or profile (#28).

### Fixed
- `cua_look` counts only the page, not the browser's menu bar, on windows without a web area (#27, pending).

### Known issues
- Tested live against a local source build of Cua Driver 0.31.0; the signed 0.31.0 release was not yet published.
