# Changelog

Versions follow Cua Driver minor releases (0.31 targets Cua Driver 0.31).

## 0.31.0 (unreleased, integration/0.31)

### Breaking / behavior changes
- `close_tab` presses the tab's own Close button in the tab strip (AX, background, no fronting, no `allow_foreground`); zero or several matching tabs refuse `tab_close_control_not_found` / `tab_close_control_ambiguous` before any press. Cmd+W (foreground) remains only as an explicit `allow_foreground: true` fallback when the strip shows no such control (#4).

### Added
- `goto {url, expect}` plan step: navigates the window's active tab in the user's own browser profile and is done only when the tab reports the requested page; typed stops `navigated_elsewhere`, `login_wall`, `landing_unknown`, `browser_tab_ambiguous` (CE-FACADE-007, #28).
- `open_tab {url, expect}` and `close_tab` plan steps; `close_tab` closes only the tab this facade opened (CE-FACADE-007, #28).
- A Driver refusal to attach to the browser profile is `permission_required` naming `--grant existing-profile`; the facade never switches to another browser or profile (#28).
- Call-budget scenarios `nav_goto_look_plan` (3 calls), `nav_open_tab_read_close` (3) and `nav_permission_required_stop` (1, nothing delivered), CE-FACADE-007 (#35). The `cua_do` step schema now accepts `url` for goto/open_tab (it was rejected as an extra field).
- SKILL.md and the MCP instructions: a short web workflow (goto/open_tab, look, plan, close_tab) and any refusal (`permission_required`, `foreground_required`, `pointer_not_deliverable_in_background`, `tab_close_control_not_found`) is stop-and-ask, never a reroute; the default-chooser text now matches the code (`CUA_GENERIC_PROVIDER`, else profile: `local-mac` Julia-1 / `fleet` Jev, else Jev) (#36).

### Removed
- The unqualified Qwen chat-completion vision fallback in `workers/visual_worker.py`: without `CUA_SYSTEMONE_URL` the visual provider is unavailable, nothing is sent, verification ends unverified and visual choose defers (#8).

### Fixed
- `cua_look` counts only the page, not the browser's menu bar, on windows without a web area (#27, pending).

### Known issues
- Tested live against a local source build of Cua Driver 0.31.0; the signed 0.31.0 release was not yet published.
