# Extraction validation

Validated from the dedicated repository on 2026-09-27:

- Offline simulation gate: 28/28 scenarios, 40/40 metamorphic variations, 20/20 dispatch unit/contract tests, 35/35 historical replay decisions, seven/seven wrong repairs rejected.
- Selector/provider suite: 15/15 tests.
- Skill and README relative links resolve; provider module compiles.
- No model loading, credentials or desktop actions required for these checks.
- Source files remain in homelab-infra. The extraction is a local Git repository, with no remote created or publication performed.

Live provider transport after portability edits and full Driver execution were not rerun. Existing inference evidence describes the source experiment. Parent-directory ba/sg executables were unavailable; source review and the recorded test gate were used, with no claim of external review.

The stock skill validator could not run because available Python environments lack PyYAML. Required name/description frontmatter and resource links were checked directly; no validator success is claimed.

## Publication preparation

README now documents multi-model dispatch and setup. `npx skills add . --list` discovered the skill; a project-scoped `--copy --agent codex --yes` installation in a temporary directory succeeded, including resolvable setup and sketch references. Sketch synchronization check and all offline gates passed again. Test-generated timing changes were discarded to retain the historical evidence.
