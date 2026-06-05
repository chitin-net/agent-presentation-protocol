# Disclaimer — Hardware Examples

**Last updated:** June 2026

## Community Reference Code — Not a Supported Product

The hardware examples in this directory are **community reference implementations** provided by Chitin, LLC to demonstrate how the Agent Presentation Protocol (APP) can be used with embedded platforms and single-board computers. They are offered as starting points for developers and makers who are already experienced with their target platforms.

**These examples are provided "as-is" without warranty of any kind, express or implied.** Chitin, LLC has not tested this code on physical hardware and makes no representations or warranties regarding its correctness, completeness, reliability, or suitability for any purpose.

## What This Means

### We cannot help you with:
- Compiling, flashing, or uploading code to your specific board
- Wiring, soldering, pin assignments, or electrical connections
- Platform toolchain issues (Arduino IDE, PlatformIO, MicroPython, CircuitPython, etc.)
- Board-specific hardware bugs, driver issues, or firmware incompatibilities
- WiFi connectivity, network configuration, or firewall problems on your local network
- Damage to your hardware, connected devices, or any other property

### What we _do_ support:
- The **APP specification** ([SPEC.md](../SPEC.md)) — the authoritative reference for message types, Agent Card schema, and relay behavior
- **Protocol-level questions** — if you're unsure how to structure an Agent Card, what fields a `device_action` contains, or how capability negotiation works, we're happy to help at support@chitin.net

In short: we own the protocol. We don't own your hardware or your toolchain — and the examples don't require any hosted relay (run the reference relay locally, or use any conforming relay).

## Safety

**You are solely responsible for the safe operation of any hardware you build or modify using these examples.** This includes but is not limited to:

- Verifying that wiring diagrams and pin assignments are correct for your specific board revision before applying power
- Ensuring adequate electrical protection (current limiting resistors, voltage regulation, proper grounding)
- Evaluating whether any connected actuators, motors, relays, or other output devices are safe to operate via remote commands
- Understanding that a device connected to a relay can receive commands from any authenticated APP surface on your account — treat this like any other remote-access system and secure it accordingly
- Not using these examples to control safety-critical systems (medical devices, life-safety equipment, heavy machinery, vehicles, or anything where a malfunction could cause injury or death)

## Security Considerations

These examples are intentionally simplified for clarity. Before deploying anything beyond a personal hobby project, you should:

- **Use secure WebSocket connections (wss://)** — some examples use `ws://` in comments or local development; always use TLS in production
- **Validate TLS certificates** — several embedded platforms have limited certificate validation; understand the implications for your threat model
- **Protect your bridge pairing token** — it provides full access to send and receive messages on your relay account. Never commit tokens to version control, never share them publicly, and rotate them if compromised
- **Restrict available actions** — only expose actions you're comfortable being triggered remotely. The relay's intelligence layer will attempt to execute any action declared in your Agent Card
- **Audit the `run_command` action** — the Raspberry Pi example includes a safe-command allowlist, but you should review and restrict this to your own comfort level

## Intellectual Property

These examples are released under the [Apache License 2.0](../LICENSE). You are free to use, modify, and distribute them, including in commercial products, subject to the terms of that license.

The APP specification is also Apache 2.0. The Chitin relay service, Chitin apps, and Chitin brand are proprietary to Chitin, LLC.

## Limitation of Liability

To the maximum extent permitted by applicable law, Chitin, LLC shall not be liable for any direct, indirect, incidental, special, consequential, or exemplary damages arising out of or in connection with the use of these examples, including but not limited to damages for loss of profits, data, equipment, or business interruption, even if Chitin, LLC has been advised of the possibility of such damages.

This limitation applies regardless of the theory of liability (contract, tort, negligence, strict liability, or otherwise) and regardless of whether the damages arise from the use or inability to use these examples, unauthorized access to or alteration of your hardware or data, or any other matter relating to these examples.

## Contributing

If you test these examples on real hardware and find bugs, we welcome pull requests and issue reports. Community contributions help everyone — and if your fix works, we'll credit you in the changelog.

## Contact

For protocol questions: support@chitin.net

For hardware questions: we recommend the community forums for your specific platform ([Arduino Forum](https://forum.arduino.cc/), [Raspberry Pi Forums](https://forums.raspberrypi.com/), [Adafruit Discord](https://adafru.it/discord), [Home Assistant Community](https://community.home-assistant.io/)).

---

*Chitin, LLC — Huntsville, Alabama*
