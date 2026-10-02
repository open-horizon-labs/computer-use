# Android false-state capture

Captured 2026-10-02 from the owned OHMixedBenchmark20261002 Android 15 emulator on a virtual display, with pinned mobilecli 1.0.16 `dump ui --format raw`. The agent task on candidate a156b17 refused the fresh Dark theme switch because the formatted element JSON omitted false checked state. This complete Display page hierarchy retains explicit `checkable: true, checked: false`; the actual switch bounds are observed, not estimated from its label. No working user device or accounts were read. The fixture is an offline regression, not measured model accuracy.
