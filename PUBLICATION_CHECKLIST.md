# Public release readiness — SBOC. 0.2.33

**Status: Stable source package prepared for first public release; not approved for Internet-facing deployment.** This document distinguishes completed source checks from tests and permissions that still need confirmation. A source-only inspection cannot establish runtime safety.

## Confirmed in this release archive

- [x] README, changelog, contribution guide, and security limitations are included.
- [x] PolyForm Noncommercial 1.0.0 license text and a project-specific M3ro-3D notice are included.
- [x] Installer banner and Python version report 0.2.33.
- [x] Syntax checks pass for Python sources and the installer (`bash -n`).
- [x] Source archive contains no runtime configuration, database, private keys, or backup files.
- [x] Basic pattern scan of this release archive found no obvious embedded secrets or private IP addresses. **Not a security audit.**

## Must verify before switching the repository to Public

- [ ] Inspect every reachable Git ref and perform a comprehensive secret scan before publishing existing history.
- [ ] If replacing history with a clean initial commit, confirm that old branches, tags and GitHub releases do not expose the private history.
- [x] Project branding identified and excluded from separate reuse under the software license; confirm any trademark concerns separately if applicable.
- [x] Add `THIRD_PARTY_NOTICES.md` with upstream references and licensing information for Sora, `rpi_ws281x`, and `cryptography`. The font files are **not included** in the source archive.
- [ ] Verify the exact Sora font release and its license, and include the required license text if fonts are redistributed. The installer currently downloads without hash verification.
- [x] Controller UI, device metrics, login persistence and agent pairing/metrics were tested on the development installation. Agent update and fresh-install coverage are not independently verified.
- [ ] Test a fresh controller installation and fresh agent installation on actual hardware. First-admin setup, login and agent pairing have passed isolated integration tests.
- [ ] Replace the old private Git history with a clean first public commit, after inspecting the actual remote refs and confirming the intended changes.
- [ ] Confirm no local/private config files are staged for commit (`git status`, `git diff --cached --name-only`).
- [ ] Decide whether the documented security limitations are acceptable for publication; the software must remain restricted to a trusted LAN, with no port forwarding. See `SECURITY.md`.

## Strongly recommended before wider distribution

- [x] Added automated local tests for bootstrap, login/logout, network destination policy, DNS-pinned requests, redirects, agent pairing, AES-GCM transport, HA-token redaction and SMTP TLS mode. Migration and physical hardware tests remain open.
- [x] Reviewed network-target validation/SSRF, root privileges and dependency integrity. Agent/HA requests now use DNS-pinned LAN-only connections with no redirects or proxies; remaining risks are documented in SECURITY_AUDIT.md.
- [ ] Verify failure/rollback behavior on real hardware.
- [ ] Set GitHub security alerts and Private Vulnerability Reporting.
- [ ] Add repository description/topics, verify licensing display, and create a tagged release with a checksum.

## Known limitations

See `SECURITY_AUDIT.md` for the full source review and prioritized findings.

- The controller's browser login is HTTP, not HTTPS. Credentials and session cookies may be exposed on an untrusted LAN.
- Home Assistant over HTTP also lacks transport encryption.
- The web controller runs as `sboc-web`; only the separate LED service runs as root for hardware access. The user confirmed LEDs illuminate after this change.
- The installer may download font files and Python dependencies without hash pinning.
- No external security audit has been completed.

Do **not** describe this noncommercially licensed project as OSI-approved open source.
