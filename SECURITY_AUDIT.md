# SBOC. — source security review

**Scope:** Static review of the supplied SBOC. source tree, its installer, Python web controller, Linux agent, pairing/transport, persistence, and documentation. A limited set of isolated unit/integration checks was run locally. **Not** a penetration test, dependency audit, runtime scan of Overwatch, or comprehensive review of the private Git history. The review is not a guarantee of security.

## Findings (priority and evidence)

| Priority | Finding | Evidence and implications | Recommendation |
| --- | --- | --- | --- |
| **High** | Controller browser authentication and configuration use plain HTTP | `sboc/controller.py` serves HTTP on 8088; login posts password and issues `sbc_session` without `Secure`; HA tokens may be submitted over HTTP. Network observers on an untrusted LAN can intercept sessions/credentials. | Restrict to trusted LAN, never port-forward; add TLS/reverse proxy for deployments outside a physically trusted LAN. |
| **Mitigated** | Privileged LED access isolated from the HTTP server | `sboc-controller.service` runs as `sboc-web`; only `sboc-led.service` uses `User=root` and receives limited commands over a local Unix socket. The privileged LED service remains a security-sensitive component. | Maintain strict socket permissions and test upgrades/hardware. |
| **Mitigated for Agent/HA** | Arbitrary network destinations (SSRF) | Agent and Home Assistant requests use only private LAN addresses, pin the validated IP for TCP, preserve TLS hostname validation, and disable redirects and proxies. SMTP targets remain administrator-configurable, including public servers (necessary for email). | Retain a trusted-LAN-only deployment and validate on real hardware. |
| **Mitigated** | First-admin setup previously allowed any reachable client | A random local one-time code is now required (`sudo sboc-setup-code`); existing installations are unaffected. | Verify new-install workflow on real hardware. |
| **Medium** | Installer downloads unpinned code/assets | `pip install` accepts ranges; Sora is fetched from a mutable `master` path, and there is no checksum/signature verification for the downloaded files. | Pin dependencies to reviewed versions and verify hashes; verify exact font license. |
| **Medium** | Login throttling is process-local and per-IP | `Handler.failures` is an in-memory dictionary; restart clears limits; potential unbounded IP-key accumulation. | Add bounded/persistent throttling and account-aware rate limits. |
| **Medium** | Agent pairing code has limited entropy and in-process rate limit | Six digits; 10 pairing starts per 5 minutes per agent process; code rotates after success. A local/network attacker may attempt pairing or denial of service. | Keep agents on trusted LAN, add stronger provisioning protections and persistent throttling. |
| **Medium** | Agent listener and service information are available to anyone who completes pairing | Pairing replaces the prior controller key; no additional operator confirmation on the agent beyond knowledge of the code. | Make pairing authorization explicit, protect local code display, and document re-pairing effects. |
| **Medium** | Agent request replay cache is volatile | `AgentTrust.seen` is memory-only and lasts 300 seconds. A restart resets the replay set. | Document residual replay behavior; consider durable counters or short validity windows. |
| **Medium** | Web security relies on Origin and Host headers | POST requires `Origin` matching the request `Host`, but no canonical host allowlist; this does not replace TLS or protection from DNS rebinding. | Restrict hostnames/bind addresses; retain Origin checks and add DNS-rebinding protection. |
| **Low** | No broad automated security regression suite | CI currently compiles Python and runs `bash -n` only. | Add authentication, pairing, session, URL-validation and migration tests. |
| **Low** | Source contains duplicated configuration literals | `DEFAULT` duplicates `operation_mode` and `network` and `validate` repeats an assignment. | Remove duplicates during a separately tested cleanup release. |

## Existing positive controls confirmed in source

- Password hashes use PBKDF2-HMAC-SHA256 with per-user random salt and 600,000 iterations.
- Login sessions use random tokens; only SHA-256 hashes are stored in SQLite, with 12-hour expiry.
- Session cookie uses `HttpOnly` and `SameSite=Strict`; `Secure` is absent because HTTP is used.
- Controller checks `Origin` on POST requests, sets `X-Frame-Options: DENY`, CSP, `nosniff`, and `no-store` on JSON and HTML responses.
- `/api/status` and public configuration remove Home Assistant token values.
- Agent pairing uses X25519, HKDF and HMAC; metrics/catalog transport uses AES-GCM with request and response authentication.
- Unpaired plain GET `/metrics` and `/catalog` are rejected.
- Agent systemd service runs as `sboc-agent` with `NoNewPrivileges=true`, `ProtectSystem=strict`, `ProtectHome=true`.
- JSON writes use atomic replace; generated local secrets are not part of the source archive.
- No use of `shell=True`, `eval()` or `exec()` found in the reviewed application code.

## Publication decision

**Security review completed as a source review; security hardening is NOT completed.** Selected controls passed isolated integration tests. The user has confirmed that the LED hardware illuminates and login works following the privilege separation. HTTP remains unencrypted and other findings remain. A public **source-code** repository may transparently publish known limitations, but this must not be presented as a hardened, internet-accessible service. Do not expose controller port 8088 or agent port 8765 to the Internet. Address high-priority findings before encouraging broad deployment or claiming security clearance.

## Git publication hygiene

Earlier private development history should not be published without a complete review of every reachable Git reference and object.

For a clean initial public release:

1. Finish the candidate and confirm that `git status` contains only intended source/docs files.
2. Create a **new root commit** (or a fresh public repository) containing only the reviewed public release, without carrying forward the old private commit history.
3. Before rewriting `main`, preserve the private history in a separate private backup repository or local bundle, if desired.
4. Only then publish the reviewed history and create the first public version tag. A force push is destructive to other clones and must be explicitly authorized.

The state of the remote repository must be verified separately; a source archive does not establish whether any GitHub operations have been performed.

## Verification history and remaining gaps

- Isolated automated checks were reported for: one-time setup-code protection, password and session lifecycle, LAN IP filtering, DNS-pinned HTTP request and redirect rejection, agent pairing and encrypted metrics exchange, HA-token redaction, SMTP STARTTLS/SSL mode selection, and a running controller HTTP integration test.
- `bash -n install.sh` and Python compile checks passed.
- **Not independently tested here:** real Home Assistant token against a live instance, real SMTP delivery or certificate handshake, systemd installation/migration/rollback, external package download authenticity, and complete GitHub history scanning. LED illumination was confirmed by the user on a Raspberry Pi 3B; this is not a complete LED behavior or safety test.
- The controller HTTP web server runs as `sboc-web`; the isolated LED service runs as root. The user confirmed LED illumination and working login with the separated services. Full privilege-boundary penetration testing remains outstanding.
