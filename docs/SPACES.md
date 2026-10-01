# Parking a window away from the user (space-mover, issue #60)

`computer_use/spaces/space-mover.swift` is a single-file Swift helper (no Xcode project, no dependencies). Build it with
`scripts/build_space_mover.sh` (output `computer_use/spaces/bin/space-mover`, gitignored); `computer_use/spaces_client.py`
builds it on demand and wraps it. The server uses it through the agent display policy below.

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

## Agent display policy (CE-FACADE-009)

`CUA_AGENT_DISPLAY` is `off`, `auto` (default) or `required`. With `auto` and `required` the server starts the agent display
lazily at the first window it needs to park, keeps it for the server's lifetime and stops it at shutdown (not at `finish`).

- **Windows the facade creates** are parked (`spaces_client.park`, verified by bounds) right after they exist and before the
  first look or act, through `Facade.window_created(window_id)`. Today no facade path creates a window: `open_tab` and
  `read_pages` send Cmd+T to an existing window (a new tab needs no parking) and the facade launches no app. A future path that
  makes a window must call `window_created(window_id, title)` once the window exists and is titled; a park answering
  `window_not_found` (a new window is briefly missing from the AX list) is retried 12 times at 0.5 s.
- **Agent-owned apps** (`CUA_AGENT_APPS`, comma-separated app names, bundle ids or fnmatch patterns; default `qemu-system-*`,
  `Android Emulator`, `Simulator`, Chrome Beta, Canary, Chromium, Chrome for Testing): an on-screen window of one of these that
  the facade first observes in a window inventory is parked once. Shared apps (Chrome, Finder, ...) and the user's windows are
  never moved. The Driver lists app names, not bundle ids, so matching is by name unless the Driver supplies a bundle id.
- **Unavailable or untrusted helper:** `auto` continues and the response carries `agent_display_note`
  (`agent_display: unavailable (<reason>)`); `required` refuses the step with `agent_display_unavailable` before anything is
  opened or moved. The failure is cached for the server's lifetime.
- A look or do response carries `agent_display: {id, parked: true}` only in the call where parking happened. Parking adds no
  LLM-visible call. Foreground routes (`allow_foreground`, `invoke_menu`, the Cmd+W fallback) are unchanged.

### Agent browser (CE-FACADE-009)

`goto`, `open_tab` and `read_pages` default to the **agent browser**: one Chrome for Testing process with a profile folder the
server owns (`~/.cache/computer-use/agent-profile`), started only when no agent browser window exists and then kept and reused for
the server's lifetime (new tabs or navigation in that window, never a new window per task). Its window is launched inside the agent
display. Chrome restores the window placement saved in the profile over `--window-position` (measured live 2026-09-30: with a
saved `browser.window_placement` of (10,37) it opened on the built-in screen and the follow-up park failed, because AX did not yet
list the new process's window). So the launch is guarded three ways, and the user's screen is never the fallback:

- **Seed.** Before every launch (our Chrome not running; if it runs it is reused, never launched again) the profile's
  `Default/Preferences` key `browser.window_placement` is rewritten to the agent display's bounds, read from the helper at that
  moment (never an x remembered from an earlier run; the virtual display appears at a different x each time):
  `{left: x+40, top: y+40, right: x+width-40, bottom: y+height-40, maximized: false, work_area_left: x, work_area_top: y,
  work_area_right: x+width, work_area_bottom: y+height}`. The file and keys are created if missing and every other key is kept;
  any `window_placement` key in `Local State` is removed. The `--window-position/--window-size` flags stay.
- **No display, no launch.** The display must exist and its bounds be known before the launch. If not, the step is refused
  `agent_display_unavailable` (also in `auto`) with the setup hint and nothing is opened. `auto` therefore means: no agent display
  refuses browser work. Only an explicit `CUA_AGENT_DISPLAY=off` set by the user launches without a display (no seeding, no
  verification).
- **Verify, never park-after.** As soon as the process's titled layer-0 window is listed, its Driver bounds must lie wholly inside
  the display (any overlap with another display, or unknown bounds, fails). If not, the process is quit at once (SIGTERM, SIGKILL
  after 3 s), the saved placement is deleted (after the process exits, since Chrome writes its placement back as it quits) and the
  step is refused `agent_browser_misplaced`, naming the bounds seen. Nothing was navigated; the window is never left up.

- **Lifecycle (measured live 2026-09-30: 23 Chrome processes stayed alive after shutdown and the next launch forwarded into them).** Chrome
  is launched with `start_new_session=True` (its own process group, pgid recorded). `stop()` sends SIGTERM to the group, waits up to 3 s,
  sends SIGKILL to the group, then scans `ps -axo pid,command` and SIGKILLs by pid any process whose command line still contains our
  user-data-dir path (a helper outside the group, or what a forwarded launch left). `shutdown()` calls `stop()`; so does interpreter exit
  (`atexit`) as a last resort. At launch, a process already carrying our user-data-dir (stale from an earlier server) is killed the same
  way first and logged (`agent_browser_recovered_stale`, with the pids): a launch never forwards into a stale instance.
- **No session restore.** Before each launch `Default/Preferences` gets `session.restore_on_startup = 5` and `profile.exit_type =
  "Normal"`, `profile.exited_cleanly = true`; `Default/Sessions` and the files `Current Session`, `Last Session`, `Current Tabs`,
  `Last Tabs` are deleted (cookies, local and session storage stay); `--disable-session-crashed-bubble --hide-crash-restore-bubble` are
  passed. The window therefore opens with exactly one tab (the placement seeding above is kept).
- **The navigated tab is the tab.** After a navigation the Driver flags no tab active. The facade remembers the tab it last navigated
  (id, then landed url and title) and, when no tab is active and the window shows several, uses it: by id, else by exactly one url+title match
  (ids are re-minted on every bind). If it cannot be told, the step is still refused `browser_tab_ambiguous`; tabs are never closed blindly
  (the next launch repairs a many-tab window via the no-restore seeding). `read_pages` closes each tab it opens; a tab left by `open_tab`
  is the agent's to close with `close_tab`.

The same containment rule applies to any window the facade creates (`window_created`) or first observes for an agent-owned app: a
window not wholly inside the display is parked (a window that merely straddles it is no longer trusted by its centre).

- `CUA_AGENT_BROWSER=auto` (default) or `user` (the old default: the window named by `title`). `CUA_AGENT_BROWSER_PATH` names an
  installed Chromium-family executable instead of Chrome for Testing.
- Chrome for Testing is installed on demand into `~/.cache/computer-use/browsers` with
  `npx -y @puppeteer/browsers install chrome@stable --path <dir>` (bounded at 10 minutes). Without npx or on a failed download the
  step is refused `agent_browser_unavailable`, naming that command.
- A step says `profile: "user"` to use your own browser window instead (it still needs existing-profile access, else
  `permission_required`); `profile: "agent"` forces the agent browser under `CUA_AGENT_BROWSER=user`. `look` by title works on either.
  Later steps of a plan act on the window the `goto` chose.
- The Driver binds the agent browser with `browser_prepare` (`existing_profile`), which the running Driver must be allowed
  (`serve --grant existing-profile`); the profile folder is ours, so no Full Disk Access is needed. Measured live 2026-09-30 (Driver
  0.31.0, Chrome for Testing 154, `--remote-debugging-port=0`): the window opened on the virtual display, `DevToolsActivePort` was
  written in our profile, the bind was exact and `browser_navigate` worked.
- The server stops the browser and the display at shutdown. The agent browser is a fresh profile (no logins), by design.
