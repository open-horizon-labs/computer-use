# Linux support scope for the facade (issue #37)

Status: scoping only. No runtime code changes. The facade is measured on macOS only; this lists what that costs on Linux, what the Driver's Linux backend gives instead, and an ordered set of small PRs. Sources: the facade at this commit, and the upstream Driver references `docs/content/docs/reference/cua-driver/mcp-tools-linux.mdx` and `limits.mdx` (Driver 0.31.0, `trycua/cua`).

## What is not known yet

The Linux reference documents the `get_window_state` element schema (`element_index`, `role`, `label`, `value`, `enabled`, `selected`, `actions` as AT-SPI action names, `frame`, `parent_index`, `depth`) but not the role vocabulary. Every claim below about Linux role or action names is a hypothesis until a real tree is captured (task L1). Do not write role maps from AT-SPI knowledge alone: `docs/PLAN-B.md` records that macOS Chrome's real tree differed from what the docs implied.

## Support tier to claim

`limits.mdx` validates typed browser mutation on Linux X11 Chrome and Edge (and Sway with Chrome only when identity and geometry are exact). Generic GNOME/KDE Wayland is read-only or refused; Firefox and Safari have no typed mutation. So the first Linux target is **X11 (or XWayland) Chrome**. Wayland is out of scope for the first milestone except possibly read-only `cua_look`.

## macOS assumptions, Linux equivalent, smallest change

**1. Role and action names are macOS AX** (`AXWebArea`, `AXButton`, `AXLink`, `AXMenuItem`, `AXCheckBox`, `AXTextField`, `AXTable`/`AXRow`/`AXCell`, `AXHeading`, `AXStaticText`, `AXGroup`, `AXList`, action `AXPress`).
- Where: `facade/core.py:1210` (CONTROL_ROLES), `:1217`, `:1320`, `:336-337`, `:547`, `:604-606`, `:697-698`, `:988`, `:1504`; `facade/look.py:26-30`, `:47`, `:66`, `:103`, `:234-273`, `:311`; `facade/ax_aliases.py:37-44`; `facade/plan.py:367`.
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
- Where: `facade/browser.py:158`, `:189-191`, `:200-215`, `:244-264` (literal `['cmd','t']` at `:205`, `['cmd','w']` at `:256`; error text at `:202`, `:215`, `:247`, `:250`, `:264`).
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
- Where: `facade/browser.py` (whole file).
- Linux: same typed tools, validated on X11 Chrome; generic Wayland is refused.
- Smallest change: none expected; check `NEW_TAB_URLS` (`browser.py:162`) against Linux Chrome's actual new-tab URL in the fixture.

Also watch: `look.py` budgets and `CALL_BUDGET.json` come from macOS Chrome trees (`facade/fixtures/real`); Linux trees may differ in node count, so the call budget needs its own Linux measurement and must not borrow macOS numbers.

## Captured Linux Chrome fixtures needed

Same pages and method as `facade/fixtures/real/` (read-only capture with the facade's own `Driver.observe`, sanitised, raw Driver element format, no clicks), stored under `facade/fixtures/linux/`:

1. `booking`, `orders`, `invoices` (list, table, cards): record-discovery shapes.
2. `flat_ax`, `nested`, `form`, `wizard`, `destructive`: control and confirmation shapes.
3. `canvas`, plus `canvas.regions.json` only if Perception exists on Linux (else `canvas` alone, to pin the degraded route).
4. A window with several tabs (for `tab_state`), a new-tab page, and an empty or thin tree (Cinnamon or AT-SPI off) to pin the failure message.
5. Per capture, the raw fields the facade reads: `window_bounds`, `screenshot_width/height`, `frame`, `background_input`, and `list_windows` for that window. Record session type (Xorg or XWayland), desktop environment, Chrome version, Driver version, display scale.

Capture is a live desktop run and needs fresh user consent each time; it needs a Linux machine or VM with X11.

## Android emulator (#27) on Linux

Validate it separately, later. The emulator is an ordinary Linux window, but what a window tool sees is a pixel surface, not Android's accessibility tree, unless another backend drives it. Linux CI also often lacks KVM and a display. Recommendation: do not gate Linux support on #27. After L5, open a follow-up recording whether the emulator window exposes any AT-SPI tree under X11, and reuse the canvas (drawn-surface) path if not.

## Ordered task list (each one PR)

1. **L1, capture.** Capture `booking` and `orders` Chrome trees on Linux X11 plus the raw metadata, commit under `facade/fixtures/linux/`, add the role/action vocabulary to this document. First failing test: the skipped `facade/test_linux.py` test, which loads `booking.ax.json` and asserts exactly one top-level web area via `_top_web_areas`.
2. **L2, role normaliser.** A pure, table-driven `normalize_platform(elements, platform)` at the observation boundary. Test: the Linux `booking` and `orders` fixtures give the same `look` record shape as the macOS expectations in `test_real_pages.py`.
3. **L3, content scoping and thin-tree gate.** Adjust `_content_ids` if needed; add the AT-SPI-off/Cinnamon message. Test: a thin Linux tree raises the named Gap; toolbar text never enters page content.
4. **L4, geometry.** Decide `window_bounds` versus `screenshot_width/height` from L1 data and adjust `_pixel_scale`. Test: `_pixel_scale` on a Linux fixture returns the measured value or `None`.
5. **L5, platform hotkey modifier.** `cmd` versus `ctrl` in `browser.py`, messages included. Test: FakeDriver records `['ctrl','t']` for a Linux driver and `['cmd','t']` for macOS. Then a live X11 measurement of background `ctrl+w` decides whether `close_tab` still requires `allow_foreground` there.
6. **L6, setup and preflight.** `setup_facade.sh` skips Perception on non-Darwin; `check_permissions` preflight note. Test: extend `scripts/test_install_perception.py` for the unsupported-platform message.
7. **L7, Linux call budget.** Run the budget scenarios over the Linux fixtures. Per `AGENTS.md`, any new tool or mandatory step needs a CE and a `CALL_BUDGET.json` change; this plan adds neither. Then decide on the Android follow-up.

The default path (`cua_look` then `cua_do`) is unchanged by every step.
