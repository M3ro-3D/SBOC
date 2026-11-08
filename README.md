# SBOC. — Single Board Observation Computer

SBOC. monitors Linux single-board computers from a central controller. It provides a browser interface, lightweight Linux agents, optional SK6812 RGBW LED status indication, Home Assistant OS metrics via its API, and SMTP notifications.

> **LAN-only software.** SBOC. is intended for trusted local networks, not direct Internet exposure. Read [SECURITY.md](SECURITY.md) before installing.

## Architecture

- **Controller:** Python HTTP server, web UI, monitoring, email alerts; TCP port **8088**.
- **Agent:** lightweight Linux telemetry service; TCP port **8765**. Agent requests require pairing and encrypted communication; restrict the services to trusted networks.
- **Discovery:** Avahi/mDNS (`_sboc._tcp`).
- **Optional LED hardware (tested):** two SK6812 RGBW strips, 10 LEDs each, GPIO12 and GPIO13 on a Raspberry Pi 3 Model B; otherwise simulated.
- **WS2812/WS2812B RGB LEDs (untested):** potentially adaptable through the same `rpi_ws281x` library, but **not supported by the current hard-coded SK6812 RGBW configuration**. Requires the correct RGB strip type and channel configuration; do not assume plug-and-play compatibility.
- **Home Assistant OS:** system-monitor sensor data via a Home Assistant long-lived access token.

## Requirements

- Debian-based Linux with Python 3 and systemd; installer requires root privileges and uses apt if dependencies are missing.
- Controller with physical LEDs: Raspberry Pi 3 Model B and compatible SK6812 hardware.
- Other platforms may run the controller in simulation mode; hardware and platform compatibility has **not** been comprehensively verified.
- LAN connectivity between controller and agents; multicast DNS optional.

## Installation

Download a reviewed release archive, extract it, then run:

```bash
cd sboc
sudo ./install.sh
```

The installer detects an existing controller or agent by installed systemd unit files. On a new device, it asks for the role. A normal application update does **not** require rebooting.

Controller UI: `http://<controller-ip>:8088` (local/trusted network only).

**Important:** The controller web server runs as the restricted `sboc-web` user. On a Raspberry Pi 3B, a separate LED-only service (`sboc-led`) runs as root to control SK6812 hardware. The web interface uses HTTP. Do not expose it to untrusted networks; see [SECURITY.md](SECURITY.md).

## Configuration and data

Runtime configuration and the event database live under `/var/lib/sboc/`. Do not upload them to GitHub. Home Assistant access tokens and SMTP credentials may be stored in those files. The installer preserves existing data on updates.

The Home Assistant URL is entered with scheme and port, for example `http://homeassistant.local:8123`. Create a long-lived access token under **Home Assistant → User profile → Security**. See the [official Home Assistant authentication instructions](https://www.home-assistant.io/docs/authentication/).

## Updates and service commands

Run the commands relevant to the installed role. The LED service exists only on controllers with supported LED hardware.

```bash
sudo systemctl status sboc-controller sboc-agent sboc-led
sudo systemctl restart sboc-controller
sudo systemctl restart sboc-agent
```

Agent service/container discovery refreshes when the agent service restarts.

## ☕ Powered by Coffee

Some projects run on electricity. Mine run on coffee. ☕

Coffee is my fuel, and quite a few cups have already gone into building SBOC.

If you enjoy this project and would like to keep the caffeine flowing, I'd be happy about a little contribution to my coffee fund.

[![Buy Me a Coffee](https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png)](https://buymeacoffee.com/m3ro)

*No pressure, just coffee. ❤️*

## Project status

SBOC. is under active development. Known limitations are documented in [SECURITY.md](SECURITY.md).

## License

SBOC. is distributed under the [PolyForm Noncommercial License 1.0.0](LICENSE.md), with M3ro-3D as licensor. Private noncommercial use and the organizational uses explicitly permitted by that license are allowed. Other commercial use requires separate permission. This is source-available software, not OSI-approved open source.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependencies and artwork rights. **M3ro-3D retains exclusive rights to the M3ro logos and branding; they are not licensed under PolyForm.**

See [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for the source-based security assessment and open risks.

See [CONFIGURATION.md](CONFIGURATION.md) for the separation of application code and private configuration, backup guidance, and pre-push checks.

## A Note on AI-Assisted Development

**SBOC. is vibe-coded software.** Let's be upfront about that.

The author has ideas, a sense for practical software, and a passion for simple, useful interfaces. What he doesn't have is extensive programming experience, particularly in the languages used to build this project.

That's where AI comes in.

The author sees AI-assisted programming as using a tool, much like an image editor, a 3D modeling application, or a sound generator. The ideas, requirements, design decisions, and overall direction come from a human. AI helps turn them into working code.

**Knowing how to design something and knowing what makes a good design are not quite the same thing.**

AI has access to an enormous amount of theoretical knowledge about design principles, user experience, and interface development. But knowing the rules doesn't necessarily mean having the human intuition for aesthetics, simplicity, and what actually feels right to use.

An interface can follow every design guideline and still feel cluttered, confusing, or unnecessarily complicated. Recognizing that difference requires human judgment, taste, and real-world experience.

In SBOC., AI helps with implementation, but the final decisions about appearance, usability, and whether something is genuinely useful remain firmly in human hands.

**And there's a lot more to building software than generating code.**

Testing, troubleshooting, refining features, and making everything work reliably in the real world still require considerable time and effort. AI can help with these tasks, but it has limited access to actual hardware, real-world environments, and the countless little things that can go wrong outside a development environment.

SBOC. has gone through numerous iterations, tests, failures, fixes, and releases to get where it is today. And that process continues.

It's not a matter of telling an AI, *"Build me a monitoring tool,"* waiting five minutes, and walking away with a finished product. If only it were that simple.

None of this means the software is automatically good or bad. Nor does it mean that AI-generated code is free from bugs, security vulnerabilities, or questionable design decisions.

**The point of this disclaimer isn't to make excuses. It's to be transparent about how this software was created and the work that goes into it.**

Evaluate SBOC. based on what it does, how well it works, and whether it meets your needs.

Use it if you find it useful. Don't use it if you don't — whether because it doesn't meet your needs or because you're simply not comfortable using AI-generated software. That's a perfectly reasonable choice.

**Either way, I wanted you to know how SBOC. came to be, what went into making it, and who's behind the decisions. The rest is up to you. Make your own judgment.**

## First-time administrator setup

On a **new controller installation**, run `sudo sboc-setup-code` via SSH on the controller to obtain the one-time administrator setup code. Enter it when creating the first account. The code is removed after successful setup. **Existing accounts and sessions are preserved on upgrades.**

Agent and Home Assistant connections are restricted to validated local-network destinations. Redirects and proxies are disabled for those connections. See [SECURITY.md](SECURITY.md) for the limitations.

## Secure Agent Pairing

The six-digit code is temporary and is not a permanent access token. Do not share it publicly.

1. Install SBOC. on the controller and agent devices.
2. Run `sudo sboc-pairing-code` via SSH on each agent.
3. In the controller, open **Set Up Devices** and select **Pair** for an existing agent, or add a discovered agent.
4. Enter the six-digit pairing code and save the changes. The pairing key persists across restarts.

Pairing an agent again replaces its previous controller key. To switch controllers, pair the agent again. Home Assistant OS devices do not require an agent pairing code; they continue to use the Home Assistant access token.

**Security boundary:** Agent telemetry is protected using AES-GCM. The SBOC web interface and HTTP connections to Home Assistant remain unencrypted. See [SECURITY.md](SECURITY.md) for details.

## Interface languages and account settings

SBOC. is available in **English and German**. English is the default interface language. Signed-in users can switch between **English** and **Deutsch** under **User Settings → Language**. The preference is stored per account and is retained across sessions.

The **User Settings → Change password** form requires the current password and a matching new password of 12–256 characters. Changing the password invalidates the account's existing sessions; sign in again with the new password. Agent pairing is not affected.


### UI localization requirement

All future UI changes must provide complete English and German text, including dynamic messages, dialogs, help text, and accessibility labels. Both languages must be checked before release.
