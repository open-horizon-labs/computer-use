# Linux support scope for the facade (issue #37)

Status: scoping plus the first real capture (L1, below). No runtime code changes. The facade is measured live on macOS; Linux is captured on Xvfb only; this lists what that costs on Linux, what the Driver's Linux backend gives instead, and an ordered set of small PRs. Sources: the facade at this commit, and the upstream Driver references `docs/content/docs/reference/cua-driver/mcp-tools-linux.mdx` and `limits.mdx` (Driver 0.31.0, `trycua/cua`).

## Measured facts (L1 capture, 2026-10-01)

Environment: Coder workspace from template `fleet-proxmox-linux` (Proxmox VM, 4 vCPU, 4 GB, `nuc14-columbus`), Ubuntu 24.04.5, x86_64, user with passwordless sudo and apt. Xvfb `:99` (1280x800x24, plain X11, no window manager, no desktop environment), private `dbus-run-session`, `at-spi-bus-launcher`, Chrome for Testing 154.0.8037.92 with `--no-sandbox --force-renderer-accessibility`, Cua Driver 0.31.0 `linux-x86_64` release tarball (the Linux backend is installable and works headless; telemetry disabled with `cua-driver telemetry disable`). Pages: the `booking`, `orders`, `form` and `canvas` fixtures of `experiments/facade-vs-native/server.py` on `127.0.0.1:8934`. Captures: `computer_use/fixtures/linux/{booking,orders,form,canvas}.ax.json` (raw `get_window_state --json`) and `list_windows*.json`. The only edit is that `screenshot_png_b64` is replaced by a `<removed: ...>` marker (about 130 KB of base64 each); every other field is as the Driver returned it. Orders, form and canvas were opened as extra tabs in the same window, so their tab strips list 3 to 5 `page tab` nodes.

### Commands used

```sh
# on the VM (apt)
sudo apt-get install -y xvfb xauth dbus dbus-x11 at-spi2-core libatk-adaptor python3-pyatspi xdotool x11-utils jq unzip \
  fonts-liberation libnss3 libgbm1 libasound2t64 libgtk-3-0t64
# Chrome for Testing (stable) and the Driver
curl -s https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json | jq -r .channels.Stable.version
wget https://storage.googleapis.com/chrome-for-testing-public/$V/linux64/chrome-linux64.zip && unzip chrome-linux64.zip
curl -sL https://github.com/trycua/cua/releases/download/cua-driver-rs-v0.31.0/cua-driver-rs-0.31.0-linux-x86_64.tar.gz | tar xz
# session (one process tree; the bus dies with dbus-run-session, so it must stay alive)
Xvfb :99 -screen 0 1280x800x24 &
DISPLAY=:99 GTK_MODULES=gail:atk-bridge NO_AT_BRIDGE=0 ACCESSIBILITY_ENABLED=1 dbus-run-session -- bash -c '
  /usr/libexec/at-spi-bus-launcher --launch-immediately &
  (cd experiments/facade-vs-native && python3 server.py --port 8934 &)
  chrome --no-sandbox --force-renderer-accessibility --user-data-dir=/tmp/cprof --window-size=1100,700 --window-position=20,20 http://127.0.0.1:8934/booking &
  echo $DBUS_SESSION_BUS_ADDRESS; sleep 3000'
# the driver must see the same DISPLAY and DBUS_SESSION_BUS_ADDRESS
cua-driver serve --socket ~/.cache/cua-driver/cua-driver.sock &
cua-driver call check_permissions --json
cua-driver call list_windows '{"pid":<chrome pid>}' --json
cua-driver call get_window_state '{"pid":<chrome pid>,"window_id":<id>,"timeout_ms":5000}' --json
```

`cua-driver call` needs a running `serve` daemon on Linux (without it: "daemon is not running ... Start it first"). `check_permissions` returned `atspi: true, x11: true, wayland: false, xsend_event: true`. Chrome's `--force-renderer-accessibility` was set, so this does not show whether the Driver alone would make Chrome build its web tree; that is unmeasured.

### Vocabulary (4 captures, 341 elements)

- Roles are AT-SPI names in lower case with spaces, not `AX*`: `frame`, `panel`, `section`, `tool bar`, `push button`, `entry`, `page tab`, `page tab list`, `document web`, `heading`, `link`, `list`, `list item`, `table`, `table row`, `table cell`, `column header`, `form`, `canvas`, `paragraph`, `alert`, `statusbar`. A checkbox, menu item or text input beyond `entry` did not occur in these pages.
- Web root: role `document web`, one per window (the active tab's document), label = page title. The node itself has no `in_web_content`; its descendants do (`in_web_content: true`), and browser chrome (frame, tool bar, page tab, address `entry`) never does. So Linux has both a root role and a per-node flag.
- Action names: `press` on `push button`, `link` and other pressables, `open` on the Chromium menu button, `activate` on the address bar `entry`, `click` on the canvas, `doDefault` and `showContextMenu` on nearly every node (so `doDefault` is not evidence of a control), `scrollUp/Down/Left/Right/Forward/Backward` on `document web`. There is no `AXPress`.
- Labels: containers often carry U+FFFC object-replacement characters (`"￼￼"`, one per child) instead of text; `table cell` labels join their child text (`"Track Cancel"` for a cell holding two buttons); the Chrome menu button is labelled `Chromium` although the binary is Chrome for Testing; `list item` labels are the record's accessible name (`Slot s01`) while the record's lines are `section` children. `selected` is present on `list item` and `page tab`. A Chrome infobar (`alert`, label `Infobar`) appears because of `--no-sandbox`.
- Fields per element: `element_index`, `element_token`, `role`, `label`, `enabled`, `actions`, `parent_index`, `depth`, `frame`, `screenshot_frame`, optional `description`, `selected`, `in_web_content`. No `value` appeared on these pages (no filled input).

### Geometry

- `window_bounds` is present: `{x:20, y:20, width:1100, height:700}`, equal to `list_windows` `bounds`.
- `coordinate_frame: "window"`, `screenshot_width/height` 1100x700 (no downscale, `frame_scale` absent), so screenshot pixels equal screen pixels: scale 1.
- `elements[].frame` is screen-absolute (`frame` of the top node is `x:20,y:20`); `screenshot_frame` is window-local (`x:0,y:0`). Frames can exceed the window (a list of height 1553 in a 557 px viewport): off-screen rows are still reported.
- No `background_input` block in any capture. The `walk_elapsed_ms` of 218 to 307 ms (booking with the default `timeout_ms` of 1000, the rest with 5000) fits the default for these small pages; larger pages need the facade to pass a larger `timeout_ms` (not done today).
- `list_windows` also lists a full-screen `Cua.AgentCursorOverlay.default` window with empty `app_name`; `app_name` of Chrome is `Chromium-browser`. Window titles end with ` - Google Chrome for Testing`.

### Consequences for the plan (hypotheses above that are now settled or changed)

- Item 1: the role map is `document web` to `AXWebArea`, `push button` to `AXButton`, `entry` to `AXTextField`, `table cell` to `AXCell`, `page tab` to a tab role, and so on; action `press` to `AXPress`. `Facade._top_web_areas` finds 0 web areas on the raw tree (pinned by `computer_use/test_linux.py`).
- Item 2: both signals exist; the normaliser maps `document web` and `_content_ids` can also use `in_web_content`. Toolbar nodes are already outside the page subtree (item 3).
- Item 4: `window_bounds` exists on Linux, so the fallback to `screenshot_width/height` is not needed for this build; the two upstream pages were wrong about its absence.
- Items 6, 7, 8, 11: not measured here (no hotkeys sent, no clicks, no foreground probes, no CDP). Still open.
- Not captured: `invoices`, `wizard`, `destructive`, a thin or empty tree (AT-SPI off), a new-tab page, a tree on Wayland or a desktop environment such as Cinnamon, and Perception on Linux.

## Support tier to claim

`limits.mdx` validates typed browser mutation on Linux X11 Chrome and Edge (and Sway with Chrome only when identity and geometry are exact). Generic GNOME/KDE Wayland is read-only or refused; Firefox and Safari have no typed mutation. So the first Linux target is **X11 (or XWayland) Chrome**. Wayland is out of scope for the first milestone except possibly read-only `look`.

## macOS assumptions, Linux equivalent, smallest change

**1. Role and action names are macOS AX** (`AXWebArea`, `AXButton`, `AXLink`, `AXMenuItem`, `AXCheckBox`, `AXTextField`, `AXTable`/`AXRow`/`AXCell`, `AXHeading`, `AXStaticText`, `AXGroup`, `AXList`, action `AXPress`).
- Where: `computer_use/core.py:1210` (CONTROL_ROLES), `:1217`, `:1320`, `:336-337`, `:547`, `:604-606`, `:697-698`, `:988`, `:1504`; `computer_use/look.py:26-30`, `:47`, `:66`, `:103`, `:234-273`, `:311`; `computer_use/ax_aliases.py:37-44`; `computer_use/plan.py:367`.
- Linux: elements carry AT-SPI roles and AT-SPI action names in `actions`; exact strings unknown until captured.
- Smallest change: one normalisation layer at the observation boundary (`Facade._observe_once`, `core.py:228-265`) that maps Linux role and action names to the AX names the rest of the code uses, selected by a platform flag. Do not fork the role sets.

**2. Page content is the first top-level `AXWebArea` subtree.**
- Where: `core.py:1213-1228` (`_top_web_areas`, `_content_ids`), used at `core.py:221`, `:1316`; `look.py:170`; `plan.py:377`, `:398`.
- Linux: the macOS tree marks web content (`in_web_content`, see the `test_real_pages.py` docstring); whether Linux Chrome exposes a document role, a flag, or neither is unknown. Chrome only builds its web accessibility tree when AT-SPI is advertised; the Driver does that, except on Cinnamon (`limits.mdx`, "Cinnamon disables accessibility advertisement"), where trees can be empty.
- Smallest change: after L1, if a web-area role exists the normaliser maps it to `AXWebArea` and nothing else changes. If not, `_content_ids` gets a second rule (the document node's subtree) behind the same function; its existing fallback is "every node", the safe failure. Add a gate so an empty or `THIN_PAGE_NODES` tree on Linux names the AT-SPI/Cinnamon cause.

**3. Menu-bar noise** (hundreds of `AXMenuItem` from Chrome's macOS menu bar).
- Where: `core.py:1226`, `:1504`.
- Linux: Chrome has no global menu bar; its chrome is a toolbar and tab strip.
- Smallest change: none expected; the fixture must show `_content_ids` still excludes toolbar and tab strip.

**4. Window geometry.** `window_bounds` from `get_window_state`, AX `frame` in points, `_pixel_scale` mapping frame to screenshot pixels.
- Where: `core.py:253`, `:395-416` (`_pixel_scale`), `:429-476` (`record_context_perception`).
- Linux: `limits.mdx` ("elements[].frame is screen-absolute") says Linux and Windows frames are physical pixels, screen-absolute, and that Windows and Linux report `screenshot_width`/`screenshot_height` but not `window_bounds`; the Linux `get_window_state` reference does list `window_bounds`. The two upstream pages disagree, so measure. The scale is normally 1 on Linux. GTK4 reports (0,0) over AT-SPI but the Driver corrects it.
- Smallest change: `_pixel_scale` already returns `None` (refuses to mix AX and Perception) when bounds are missing, which is the safe default. If L1 shows `window_bounds` absent, fall back to `screenshot_width/height` against `list_windows` `windows[].bounds`. Record grouping uses only relative y inside one snapshot (`core.py:451-465`), so screen-absolute versus window-local frames do not matter there.

**5. Cua Perception.** Installer targets macOS Apple Silicon; status via `cua-driver extension status cua-perception`.
- Where: `scripts/install_perception.py:36` (platform table), `:63-68`; `scripts/setup_facade.sh` (Perception step); `core.py:51`, `:78-88`, `:174-181`, `:343-357`.
- Linux: the reference lists `install_extension` (name `perception`) and `parse_visual_regions(capture_id)`; whether the artifact is published for Linux is not stated.
- Smallest change: treat as unavailable. `perception_state` already degrades to `not_installed` and every Perception path raises a Gap naming the installer. `setup_facade.sh` should skip Perception with a clear message on non-Darwin (or pass through to `install_extension`) instead of dying on "Unsupported platform". Canvas pages then rely on `allow_foreground` plus the screenshot model, as they do today without Perception.

**6. Hotkeys Cmd+T and Cmd+W.**
- Where: `computer_use/browser.py:158`, `:189-191`, `:200-215`, `:244-264` (literal `['cmd','t']` at `:205`, `['cmd','w']` at `:256`; error text at `:202`, `:215`, `:247`, `:250`, `:264`).
- Linux: `hotkey` takes `["ctrl","t"]` and `["ctrl","w"]`. On X11, background hotkeys reach the target without focus steal. WM chords (`super+*`, `alt+tab`, `ctrl+alt+*`) are refused with `wm_chord_unavailable`; `ctrl+t/w` are application shortcuts, not WM chords. Chrome may still ignore some accelerators in the background (macOS `Cmd+W` needed foreground); Linux is unmeasured.
- Smallest change: choose the modifier from the Driver platform (`cmd` on macOS, `ctrl` elsewhere) and fix the messages. Measure background versus foreground for both on X11 Chrome before deciding whether `close_tab` keeps requiring `allow_foreground` there.

**7. `delivery_mode` foreground semantics** ("fronts the window briefly, then restores your app").
- Where: `core.py:132`, `:1086-1094` (pixel click on a drawn surface forced to foreground), `plan.py:103-104`, `:470`, `:504-509`; `browser.py:188-191`; `docs/FACADE.md`.
- Linux: same parameter. A background pixel click on X11 resolves the AT-SPI element under the point first, else presses a virtual pointer, so the macOS "lands at the element's centre" behavior may not apply. Foreground on X11 is `_NET_ACTIVE_WINDOW` then restore; on Wayland it needs a compositor adapter and can refuse. Native Wayland background keyboard to a non-editable field returns `background_unavailable`. `browser_dialog` on Linux Chromium requires foreground.
- Smallest change: no code change for X11. Re-run the CE-FACADE-006 probe (background canvas click) on Linux; the `pointer_not_deliverable_in_background` refusal may be over-strict there, but keep it until measured. Map `background_unavailable` to a Gap that names `allow_foreground`.

**8. `needs_foreground`** (window on another Space or AX-unresolved).
- Where: `core.py:277-294`, `:50` (`MIN_DRIVER_VERSION`), `docs/FACADE.md:266`.
- Linux: `exact_window` and `off_space_or_ax_unresolved` are macOS concepts; Linux workspaces are not special-cased upstream.
- Smallest change: `check_foreground` only fires when a `background_input` block with a non-`matched` status is present, so it is a no-op on Linux unless the Driver emits one. Check the fixture for that block; add no Linux logic unless it appears.

**9. TCC and install layout.** Accessibility and Screen Recording grants tied to `CuaDriver.app`; driver at `~/.local/bin/cua-driver`; calls via `cua-driver call <tool> --json`.
- Where: `core.py:61`, `:69`, `:94`; `docs/LOCAL-MAC.md`; `limits.mdx` ("Permission boundaries").
- Linux: `check_permissions` and `health_report` (`ax_capability` via AT-SPI, `screen_capture_capability` via X11) replace TCC. Bare `cua-driver mcp` owns its runtime on Linux. Wayland needs RemoteDesktop portal grants and libei.
- Smallest change: the CLI (`call`, `extension status`) is platform-neutral in the facade; add a Linux setup note and a preflight that runs `check_permissions`/`health_report`. Confirm the `call` and `extension status` subcommands exist on the Linux build. No change to `core.py` paths.

**10. `scripts/setup_facade.sh`.** Plain bash, uv/venv; only the Perception step is macOS-specific (item 5). Smallest change: guard that step by `uname`.

**11. Browser CDP path** (`browser_prepare`, `get_browser_state`, `browser_navigate`).
- Where: `computer_use/browser.py` (whole file).
- Linux: same typed tools, validated on X11 Chrome; generic Wayland is refused.
- Smallest change: none expected; check `NEW_TAB_URLS` (`browser.py:162`) against Linux Chrome's actual new-tab URL in the fixture.

Also watch: `look.py` budgets and `CALL_BUDGET.json` come from macOS Chrome trees (`computer_use/fixtures/real`); Linux trees may differ in node count, so the call budget needs its own Linux measurement and must not borrow macOS numbers.

## Captured Linux Chrome fixtures needed

Same pages and method as `computer_use/fixtures/real/` (read-only capture with the facade's own `Driver.observe`, sanitised, raw Driver element format, no clicks), stored under `computer_use/fixtures/linux/`:

1. `booking`, `orders`, `invoices` (list, table, cards): record-discovery shapes.
2. `flat_ax`, `nested`, `form`, `wizard`, `destructive`: control and confirmation shapes.
3. `canvas`, plus `canvas.regions.json` only if Perception exists on Linux (else `canvas` alone, to pin the degraded route).
4. A window with several tabs (for `tab_state`), a new-tab page, and an empty or thin tree (Cinnamon or AT-SPI off) to pin the failure message.
5. Per capture, the raw fields the facade reads: `window_bounds`, `screenshot_width/height`, `frame`, `background_input`, and `list_windows` for that window. Record session type (Xorg or XWayland), desktop environment, Chrome version, Driver version, display scale.

Capture is a live desktop run and needs fresh user consent each time; it needs a Linux machine or VM with X11.

## Android emulator (#27) on Linux

Validate it separately, later. The emulator is an ordinary Linux window, but what a window tool sees is a pixel surface, not Android's accessibility tree, unless another backend drives it. Linux CI also often lacks KVM and a display. Recommendation: do not gate Linux support on #27. After L5, open a follow-up recording whether the emulator window exposes any AT-SPI tree under X11, and reuse the canvas (drawn-surface) path if not.

## Ordered task list (each one PR)

1. **L1, capture (done for booking, orders, form, canvas; see "Measured facts").** Capture `booking` and `orders` Chrome trees on Linux X11 plus the raw metadata, commit under `computer_use/fixtures/linux/`, add the role/action vocabulary to this document. `computer_use/test_linux.py` now pins the measured shape, including that `_top_web_areas` finds 0 web areas on the raw Linux tree.
2. **L2, role normaliser.** A pure, table-driven `normalize_platform(elements, platform)` at the observation boundary. Test: the Linux `booking` and `orders` fixtures give the same `look` record shape as the macOS expectations in `test_real_pages.py`.
3. **L3, content scoping and thin-tree gate.** Adjust `_content_ids` if needed; add the AT-SPI-off/Cinnamon message. Test: a thin Linux tree raises the named Gap; toolbar text never enters page content.
4. **L4, geometry.** Decide `window_bounds` versus `screenshot_width/height` from L1 data and adjust `_pixel_scale`. Test: `_pixel_scale` on a Linux fixture returns the measured value or `None`.
5. **L5, platform hotkey modifier.** `cmd` versus `ctrl` in `browser.py`, messages included. Test: FakeDriver records `['ctrl','t']` for a Linux driver and `['cmd','t']` for macOS. Then a live X11 measurement of background `ctrl+w` decides whether `close_tab` still requires `allow_foreground` there.
6. **L6, setup and preflight.** `setup_facade.sh` skips Perception on non-Darwin; `check_permissions` preflight note. Test: extend `scripts/test_install_perception.py` for the unsupported-platform message.
7. **L7, Linux call budget.** Run the budget scenarios over the Linux fixtures. Per `AGENTS.md`, any new tool or mandatory step needs a CE and a `CALL_BUDGET.json` change; this plan adds neither. Then decide on the Android follow-up.

The default path (`look` then `do`) is unchanged by every step.
