# Security policy

TimeCanvas is designed to run on a private network (the reference install is reachable only over Tailscale). The threat model, the controls, what runs as root and the inventory of secrets are in [docs/SECURITY.md](docs/SECURITY.md).

## Reporting a vulnerability
Please report it privately, using GitHub's "Report a vulnerability" (private security advisory) on this repository, and do not post details in a public issue. Include the version (`Settings > Maintenance`), what you did, and what happened. Expect an acknowledgement; there is no bug bounty.

## Supported versions
Only the latest tagged release (see [CHANGELOG.md](CHANGELOG.md)) receives fixes.
