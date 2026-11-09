# SBOC. security and deployment limits

- Do **not** forward ports 8088 or 8765 to the Internet. Keep them on a trusted LAN.
- Controller web login and setup use HTTP by design; passwords, session cookies, and newly submitted Home Assistant tokens are not protected by TLS on that connection. This is a deliberate limitation, not a claim of end-to-end encryption.
- Controller–agent application messages use authenticated AES-GCM after X25519-based pairing with a six-digit code. Pairing requests and service discovery remain network-visible. Rate limiting reduces but cannot eliminate pairing attacks.
- Agent `/metrics` and `/catalog` are not publicly accessible without authenticated secure requests.
- The privileged LED driver runs separately from the unprivileged controller web process. The LED driver exposes a local Unix socket to the `sboc-web` group.
- Controller state under `/var/lib/sboc/` can contain Home Assistant tokens, SMTP credentials, login hashes, and agent trust keys. Agent state under `/var/lib/sboc-agent/` contains pairing secrets. Never publish either directory.
- Home Assistant HTTP connections send HA tokens without TLS. Use HTTPS on Home Assistant when available, or accept the local-network risk.
- Sora fonts and optional Python packages are downloaded from external sources at install time. Their availability and upstream integrity are external dependencies; releases are not fully reproducible without pinned hashes.
- A successful source-level audit does not establish the absence of vulnerabilities. Physical deployment and third-party integration testing remain necessary.

Report security concerns privately to the repository maintainer; avoid including credentials or personal addresses in public issues.
