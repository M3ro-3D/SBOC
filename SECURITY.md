# Security and limitations — SBOC.

SBOC. is designed for **trusted local networks**. Ports 8088 and 8765 must **not** be exposed to the Internet. SBOC. does not manage TLS certificates or enforce HTTPS.

## Agent communication

- Pairing uses a six-digit code displayed **locally on the agent** with `sudo sboc-pairing-code`.
- Initial pairing performs an X25519 key exchange with HKDF-SHA256 derivation bound to the code and mutual HMAC-SHA256 confirmation. The code is not transmitted over the network.
- Metrics and catalogs are subsequently transmitted using AES-256-GCM encryption. Nonces and a time-limited replay cache prevent repeated requests during a running agent session.
- Direct, unprotected requests to `/metrics` and `/catalog` are blocked.
- Each agent trusts one controller at a time. Pairing again replaces that trust key; the new connection must then be saved on the controller.
- Pairing attempts are rate-limited to 10 starts per five minutes within the running agent process. This is **not comprehensive protection against attacks or a local adversary**.

## Home Assistant and browser

- Home Assistant tokens are stored in `/var/lib/sboc/config.json` and are not returned to the browser through `/api/status` or `/api/config`. Existing tokens are retained when settings are changed without supplying a replacement token.
- Login and the web interface still use **HTTP**. A compromised LAN can expose usernames, passwords and session cookies in transit.
- When Home Assistant is connected over HTTP, its token is **not encrypted in transit**. Agent transport encryption does not protect the Home Assistant connection.
- Entering a new Home Assistant token in the browser sends it to the controller over HTTP.

## Other security considerations

- **Privilege separation:** The web server (`sboc-controller.service`) runs as the restricted `sboc-web` user. Only the separate LED service (`sboc-led.service`) runs as root to drive SK6812 LEDs directly. The LED service accepts limited pixel commands through a local Unix socket. This privileged service remains a potential attack surface. Run SBOC. only on a trusted LAN and do not forward its ports.
- The installer may download fonts and Python packages from the Internet. Dependencies are not yet pinned with integrity hashes.
- Home Assistant and agent connections are restricted to private LAN addresses. The resolved destination IP is pinned for each connection, and HTTP redirects and proxies are disabled for these connections. SMTP is deliberately exempt because mail servers are often hosted on the public Internet. Authenticated administrators can configure SMTP destinations.
- Creating the first account requires a random local setup code (`sudo sboc-setup-code`). Existing installations retain their accounts.
- No comprehensive independent security audit has been performed.

**Do not configure port forwarding on your router.** Please report security vulnerabilities privately through GitHub Private Vulnerability Reporting if that feature is enabled for this repository.

## Source security review

A source-based security review is documented in [`SECURITY_AUDIT.md`](SECURITY_AUDIT.md). It identifies residual risks, including HTTP transport, a separate root-running LED service, configurable SMTP destinations and dependency integrity. The current implementation includes first-admin setup protection and network destination restrictions. This is **not** an external penetration test or a clean bill of health.
