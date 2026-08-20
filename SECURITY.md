# Security policy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting flow from the repository's
Security tab. Do not open a public issue for credentials, sandbox escapes,
command injection, secret disclosure, or a way to bypass an access boundary.
If private reporting is unavailable, open a minimal issue asking the maintainers
for a private contact channel without including vulnerability details.

Include the affected revision, provider configuration shape, reproduction
steps, impact, and whether the issue requires a real provider call. Remove
tokens, private prompts, and model reasoning from every attachment.

## Supported versions

The project is currently alpha. Security fixes target the latest revision on
the default branch; no older release line is guaranteed to receive patches.

## Security boundary

The framework validates declared provider access and avoids shell invocation,
but a provider CLI and its sandbox remain part of the trusted computing base.
CLI token and dollar budgets are admission controls between calls, not hard
in-request limits. Use external isolation for untrusted repositories or
providers that cannot enforce the configured filesystem boundary.
