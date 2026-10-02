# iOS Developer hierarchy

Captured 2026-10-02 from the owned synthetic benchmark simulator (iPhone 17 Pro, iOS 26.5), Settings → Developer, using mobilecli 1.0.16 `dump ui`. The JSON preserves actual refs, hierarchy, bounds and switch state. It contains only that screen, not device inventory or credentials. The corresponding mobile-mcp 1.0.6 observation flattens this hierarchy; tapping the labeled parent Switch did not change appearance. Its observed unlabeled Switch child did. This fixture tests ancestry-bound activation and typed state verification, not general iOS accuracy or atomicity.
