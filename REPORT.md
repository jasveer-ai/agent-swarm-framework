# Scoped parallel implementation

Local, uncommitted framework changes add opt-in disjoint file ownership for concurrent writers. Existing default serialization remains in place; overlapping, ancestor and unscoped paths retain exclusion through worker completion and review. Models remain externally configured.

Task plans declare literal repository-relative `workspace_paths`; `budgets.allow_disjoint_workspace_writes` explicitly enables scoped leases. Providers must independently enforce ownership. Separate processes still need external isolation.

Verification: all 87 framework unit/integration tests passed, including default writer serialization and opt-in overlapping execution of two disjoint writers with mandatory reviews. Ruff passed on changed Python files. This does not establish app runtime, visual parity or device acceptance.

The pre-existing `.swarm/config.yaml` change was preserved. No commit or publication was performed.
