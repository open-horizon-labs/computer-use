# Optional mobile adapter

Use an available native mobile route first. Enable OH's look/do adapter only when its concrete device capability is needed; this is a capability choice, not a claim that it beats native.

Pass capability="mobile" and a concrete device ID. Discovery with device="list" does not select a device. Observe controls with look, then submit do steps with independently visible outcomes. Launch uses an explicit app identifier. A switch needs expect="checked" or "unchecked"; absent state is unknown, never assumed false. No blind coordinates or another device's cached hierarchy.

Provider setup is in [setup](setup.md). Bind a fresh observation, handle typed refusals, and stop if delivery is uncertain. Grants/credentials may need the user; ordinary stale-state recovery does not. Screen images provide evidence, not implicit action handles. Preserve explicit state and independent verification when changing providers.
