# Lightweight off-screen browsing

For a small browser-only task without user logins, use an available isolated browser capability that can stay off the physical screen. No full desktop guest is needed just to read pages or fill a simple form. Confirm the provider's isolation and observation/input support; do not assume headless or hidden means correctly isolated.

The optional OH adapter supports an owned Chromium profile on a required verified virtual display. It is useful when installed and available; it is not a measured speed winner and has not been qualified for locked-host use. Enable it only for the task through [setup](setup.md). It never substitutes the user's profile or physical screen.

Start with do(capability="off_screen", goal="Open isolated browser", steps=[{do:"open_tab", url:"https://example.com", expect:null}]). Reuse its context_id; call look before choosing visible controls, then do with independent outcomes. Reuse look_id for where.lines predicates; filters need observed evidence. A null final expect is delivered_unverified, not success. One off-screen context is active per server.

If a browser/display prerequisite fails, repair supported setup or use a task-owned Spaces guest when that satisfies the request. Do not keep retrying a broken display or silently route to the host screen. For logins in the user's browser, use OBO instead. Provider commands/secrets remain external; no specialist models or archived native/VNC/terminal routes are needed.
