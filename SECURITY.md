# Security

CapEgo is an early software prototype. The current `main` branch receives fixes; there are no supported stable-release lines yet.

For a suspected vulnerability, use GitHub private vulnerability reporting if it is enabled for this repository. Otherwise, open an issue asking maintainers for a private reporting channel without including exploit details, credentials or private recordings. Include the affected commit, a minimal reproduction, impact and relevant logs through that private channel.

The receiver binds to loopback by default. LAN binding requires `CAPEGO_TOKEN` and an explicit allowed host. Direct HTTP does not encrypt the token or recordings: use a trusted isolated LAN or a TLS reverse proxy. The workbench is a single-user prototype, not a hardened multi-tenant service.

Keep runtime data, tokens and downloaded models out of Git. Local model loading is restricted to the configured model directory with remote code and automatic downloads disabled. Prepare dependencies and models before offline operation.
