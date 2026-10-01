# Why computer-use exists

A screenshot-and-click agent pays for every step twice: once to see the screen and once to decide what to do. Both costs land in the model's context. computer-use moves most of that work out of the model and into code that checks itself.

## The problem

With stock computer-use tools, the model gets a screenshot or an accessibility dump, picks a coordinate or an element, acts, and looks again. Every step is a model turn, and model turns, not tool time, dominate a run.

Three more costs come with it:

- **The agent needs your screen.** A driver that clicks on the desktop competes with the person using it.
- **Pixels are a poor way to read text.** An OCR pass over a booking page got the layout right and the values wrong: "60 min" came back as "600 min".
- **The model is the only safety check.** Nothing outside it decides whether a click hit the right thing.

## What it does instead

### Two tools

The model sees `look` and `do`.

- `look` is read-only and runs no model. It returns the strings the page actually shows, plus a `look_id`.
- `do` takes a whole plan. The server checks the plan, then for each step re-reads the screen, binds the exact control, acts, checks the step's `expect`, and recovers from stale state on its own.

Eight finer-grained tools exist, but only behind `CUA_TASK_ADVANCED=1`. Adding a tool or a mandatory step to the default path means changing a committed call budget, and CI rejects the change if the numbers don't match.

Response budgets keep the context small. The tool list went from 32.5 KB to 23.6 KB, and responses shrank 10.7% across 54 test scenarios.

### Rules decide who reads the page

A dispatcher picks the reader:

- no model for an exact control;
- GLiNER or GLiNER2 for fields;
- Jev for a semantic choice, escalating to Qwen (fleet profile) or Julia-1 (local-mac profile).

Verification tries the exact check first. There is no trained router.

On 39 paired observations, dispatch got all 39 right with no abstentions and a 29 ms median. Jev alone got 23 right, abstained on 14 and got 2 wrong, with a 144 ms median. That corpus is small: 35 booking steps from 20 tasks. The extractor also takes 4.56 s to start, so dispatch is slower overall unless the extractor stays loaded.

### The screen is read in tiers

1. The accessibility tree, with no model.
2. In a browser, the page's DOM snapshot, capped at 6 s per call and 10 s in total. Lines that only the DOM has are shown as `dom_lines` and never acted on.
3. On-device OCR for canvases. It is never treated as the truth.

NuExtract3 page extraction is opt-in per request, through `look(fields=...)`. The test suite fails if a plain `look` starts it. It sends page content to the hosted service you configure, 10 records at a time. It took 9.1 s for 27 records and 13.7 s for 56. Its accuracy on large tables has not been measured.

### It works off your screen

On macOS, `space-mover` creates a 1920x1080 virtual display and parks the agent's own windows on it. Nothing is mirrored, so no Screen Recording permission is needed, and your windows are never moved. The agent's browser is Chrome for Testing with its own profile. It opens on that display, and if it lands anywhere else the step is refused. Input goes through background routes and never raises a window.

The trade-offs are real. The helper uses private CoreGraphics classes that can change between macOS releases. It needs an Accessibility grant. While it runs, the extra display is part of your desktop layout.

### Safety lives in code, not in the prompt

- A destructive action such as delete or pay needs the step itself to carry `allow_destructive` with the exact control label. Wording in the goal never unlocks it.
- Every step except the last carries an `expect`. A click is never retried. A `confirm` step must declare the dialog's full text and buttons.
- Everything on the page is treated as data, never as instructions.
- A refusal means stop and ask the user. The agent may not add `allow_foreground` on its own.
- A VNC password is never typed.
- Waiting for a slow page never solves or skips a check.

## What it costs

There is one head-to-head against the stock Cua Driver tools: six runs with Claude Sonnet 5.5, one per task and tool set.

| Task | Stock Cua Driver | computer-use |
|---|---|---|
| booking | correct, 15 turns, $1.14, 35 s | correct, 30 turns, $0.90, 69 s |
| orders | correct, 19 turns, $0.81, 43 s | correct, 19 turns, $0.91, 58 s |
| canvas | no action, 11 turns, $0.51, 21 s | no action, 16 turns, $0.36, 32 s |

One run per cell proves little. computer-use was cheaper on two tasks and more expensive on one, and slower on all three. The point is not cheaper runs. The point is a context that stays small and steps that are checked.

The offline gate passes 28 of 28 scenarios, 40 of 40 variants and 35 of 35 replays, and rejects 7 of 7 deliberately wrong repairs. That shows the code follows its own rules. It does not show that a model writes good plans on messy real pages. That is still open.

## What it does not do yet

- **macOS only.** Linux accessibility trees have been captured from Chrome on Xvfb, but the Linux backend is not built yet.
- **Native file pickers.** The picker exposes nothing the Driver can act on. On web pages the `upload` step sets files on the page's file input directly, so no picker opens.
- **Canvas clicks in the background.** A background click on a drawn canvas lands at the element's centre, so it is refused unless the step allows the foreground.
- **Not yet run for real:** the Mission Control fallback, `invoke_menu` and noVNC. The Android emulator has been run headless: a look, a press and a back, all checked.
- **`local-mac` has no local extractor.**

## Where it fits

computer-use works alongside a stock driver; it does not replace one. It is built on Cua Driver, mobile-mcp and Cua Perception. The virtual display and window parking follow DeskPad and PaperWM.
