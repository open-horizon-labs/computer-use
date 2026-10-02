# Cua Spaces isolated-browser qualification

Result: passed one live Linux container browser smoke test on 2026-10-02. Spaces is a credible replacement candidate for OH's isolated-browser and virtual-display plumbing. This is a functional qualification, not a comparative benchmark or a change to the native-first policy.

## Setup and execution

Installed Cua CLI 0.2.0 with `--cli-only --no-onboarding`; no GUI application, account login, host sharing, or agent configuration change. Created `local:oh-spaces-smoke-20261002` using OrbStack/Docker, two CPUs and 4096 MB memory. Image: `ghcr.io/trycua/linux@sha256:f5306ce817ba495838a362a0249bbe683afcbc3f0996b9c05714ca007bb23302`. Container creation took approximately 75 seconds after the successful create attempt, including the cold image pull. gVisor was unavailable; the CLI selected runc.

Connected through the actual `cua mcp --embedded --sandbox …` transport. Launched Chromium using Driver `browser_prepare` with `isolated_new`, obtained the guest window inventory, then bound exactly to its PID/window. Every form action used a ref from the latest semantic snapshot. Clicks explicitly used foreground delivery inside the isolated guest desktop. No host window was operated and no blind coordinates or direct HTTP submission were used.

The task entered `Birch` and `Spaces smoke`, checked `Include manifest`, clicked `Review`, verified the review text, then clicked `Confirm dispatch`. Five form actions all succeeded. Fresh observations verified each state transition; the final observation showed `Dispatch committed` and included a screenshot. A separate guest filesystem read verified the application's saved receipt exactly:

```json
{"recipient":"Birch","message":"Spaces smoke","manifest":true}
```

The local HTTP fixture was copied into the guest and started before GUI execution. Receipt creation was performed by the application after the Driver click, not by the test harness. A harness PTY line-length mistake interrupted an earlier connection before form execution; the corrected connection freshly rebound the browser. This is excluded from upstream failure claims.

## Friction observed

- Default creation refused with approximately 6.3 GiB free: its estimate required approximately 2 GiB for the image plus a 5 GiB reserve. The successful attempt used a temporary `CUA_DISK_MIN_FREE=3G` and disabled automatic cache GC. No global disk policy changed. Docker subsequently reported 4.31 GB disk usage and 1.15 GB content size for the image; those are different measurements. The estimate does not comfortably describe this host's observed disk consumption.
- The default MCP connection exposed 138 tools, totaling 106,083 bytes of compact serialized tool metadata. This is potential discovery/prompt overhead, not measured model token consumption; clients may load tools dynamically.
- The semantic browser snapshots exposed additional editable generic/static-text refs with unknown visibility. The intended labeled controls remained clear, so this did not cause a failure in this fixture.

## Limits and disposition

Not tested: locked-host execution, macOS guest applications, teleport/login transfer, mobile parity, video streaming, real-site widgets, or comparative execution time and model tokens. The screenshot path worked; that does not establish streaming. One simple form cannot establish general reliability or speed superiority.

Deleted the disposable Space and confirmed its ID was no longer found. Kept the downloaded image at the user's explicit request. The CLI remains installed. No OH runtime routes, default allowlist, or call budget changed.

Official references: [Spaces](https://cua.ai/docs/spaces), [agent integration](https://cua.ai/docs/spaces/guides/use-from-an-agent), [teleport](https://cua.ai/docs/spaces/guides/teleport-an-app), and [disk usage](https://cua.ai/docs/cua-sdk/guides/disk-usage). Live qualification above is the evidence for the pass; documentation alone is not.
