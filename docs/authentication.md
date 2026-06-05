# Authentication

The Agent Presentation Protocol (APP) supports several authentication mechanisms so that implementations can match deployment context — consumer pairing, enterprise IdP / SSO, headless and fleet-deployed surfaces, and air-gapped scenarios all have viable paths. The reference clients use the bridge pairing token flow described first; other mechanisms are equally conforming and are detailed below. See SPEC.md §3.2 and §7 for the normative summary.

| Mechanism | Primary use | Detail section |
|-----------|-------------|----------------|
| Bridge pairing token | Consumer pairing (QR-based); reference clients | [Bridge Pairing Token](#bridge-pairing-token-primary) |
| OAuth 2.0 / OIDC | Enterprise SSO, federated identity | [OAuth 2.0 / OIDC](#oauth-20--oidc-enterprise) |
| mTLS | Headless, kiosk, fleet, CAC/PIV-derived credentials | [mTLS](#mtls) |
| Pre-shared key (PSK) | Air-gapped deployments, offline operation | [Pre-Shared Key (PSK)](#pre-shared-key-psk) |
| JWT | Short-lived bearer tokens (consumer surface registration, IdP-issued) | [Surface Authentication (JWT)](#surface-authentication-jwt) |
| API key | Local development and testing | [API Key](#api-key-development) |

All mechanisms bind credentials to a specific (agent, surface) tuple at issuance and require platform-appropriate secure storage at rest. See [Credential Storage](#credential-storage) below.

## Bridge Pairing Token (Primary)

Bridge pairing tokens are persistent, non-expiring credentials that identify a specific (agent, surface) pairing. They are obtained through a QR code pairing flow. The reference clients use this method; conforming third-party clients MAY use this method or any of the other mechanisms below.

### Pairing Flow

```
Agent (Bridge)                  Relay                        Surface (App)
     │                            │                            │
     ├── POST /api/pair ─────────►│                            │
     │   (requires JWT)           │                            │
     │◄── { pairingCode: "AXRF" }─┤                            │
     │                            │                            │
     │   Display QR code          │                            │
     │   containing:              │                            │
     │   {                        │                            │
     │     "type":"chitin-bridge",│                            │
     │     "relay":"wss://...",   │                            │
     │     "bridge":"Home Mac",   │                            │
     │     "bridgeId":"uuid"      │                            │
     │   }                        │                            │
     │                            │        User scans QR code  │
     │                            │◄── POST /api/pair/claim ───┤
     │                            │    { pairingCode, appUserId }
     │                            │                            │
     ├── POST /api/pair/verify ──►│                            │
     │◄── { bridgeToken, bridgeId }                            │
     │                            │                            │
     │   Store bridgeToken        │                            │
     │   in Keychain              │                            │
     │                            │                            │
     ├── WSS /ws/bridge?token= ──►│                            │
     │                            │◄── WSS /ws/surface?token= ─┤
     │                            │                            │
     │   ✓ Paired and connected   │   ✓ Paired and connected   │
```

### QR Code Formats

The reference clients recognize two QR code formats; conforming third-party surfaces MAY accept either or both:

**Relay/Bridge QR (APP):**
```json
{
  "type": "chitin-bridge",
  "relay": "wss://your-relay.example",
  "bridge": "Home Mac mini",
  "bridgeId": "uuid"
}
```
Encoding: plain JSON string. Discriminated by `"type": "chitin-bridge"`.

**Gateway QR (OpenClaw direct, legacy):**
```
base64url-encoded JSON:
{
  "url": "ws://192.168.1.100:18789",
  "token": "gateway-token",
  "bootstrapToken": "..."
}
```
Encoding: base64url. No `type` field. Detected by attempting base64url decode.

### Detection Logic

1. Try parsing raw string as JSON
2. If it has `"type" == "chitin-bridge"` → relay QR → connect via relay
3. Otherwise try base64url decode → JSON parse → gateway QR → connect directly
4. If neither → show error

### Pairing Code Format

Codes use unambiguous characters (no 0/O, 1/I/L) and expire after 10 minutes. Format: `AXRF-7724` — designed to be easy to read aloud and type.

### Token Storage

The reference clients store bridge pairing tokens as follows. See [Credential Storage](#credential-storage) below for the full multi-platform recommendation that applies to all credential types.

| Platform | Storage | Access |
|----------|---------|--------|
| iOS | Keychain (`kSecAttrAccessibleAfterFirstUnlock`) | Persists across app launches, survives device restarts |
| macOS | Keychain (`chat.chitin.bridge.bridge`) | Separate service name from relay JWT and OpenClaw token |

Bridge pairing tokens persist until explicitly revoked by the relay operator.

## Surface Authentication (JWT)

The reference clients authenticate with the relay using JSON Web Tokens. JWT is also usable by any conforming third-party surface, and by either role (agent or surface) in enterprise flows where an IdP issues short-lived bearer tokens.

### Registration

Two paths:

**Anonymous registration:**
```
POST /api/register
{ "deviceId": "uuid-generated-on-device" }
→ { "userId": "uuid", "token": "jwt..." }
```
No email, no password. Device generates a UUID on first launch. The relay creates an account and returns a JWT. This is the default path for new users.

**Email registration:**
```
POST /api/register
{ "email": "user@example.com", "password": "..." }
→ { "userId": "uuid", "token": "jwt..." }
```

### JWT Refresh

JWTs expire. Surfaces refresh via:
```
POST /api/login
{ "email": "...", "password": "..." }
→ { "token": "new-jwt" }
```

Anonymous users re-authenticate with their deviceId.

### Cross-Device Limitation

Each device gets a separate `userId` via anonymous registration. The same human on two devices has two separate relay accounts with separate memory stores. This is a known limitation.

## OAuth 2.0 / OIDC (Enterprise)

For enterprise deployments where agents authenticate via corporate identity providers.

### Configuration

Enterprise customers configure their identity provider (IdP) with the relay operator:

- **Provider:** Azure AD, Okta, Auth0, Google Workspace, or any OIDC-compliant IdP
- **Client ID / Secret:** Registered in the IdP for the APP integration
- **Token endpoint:** Where the relay validates tokens
- **Scopes:** What access the token grants

### Flow

1. Agent obtains an access token from the corporate IdP (standard OAuth 2.0 flow)
2. Agent connects to relay with the token: `wss://your-relay.example/ws/bridge?token=<oauth-token>&auth=oauth2`
3. Relay validates the token against the configured IdP
4. If valid, the connection proceeds as normal

### Use Cases

- Enterprise agents deployed across an organization authenticate with the same IdP as other corporate tools
- SSO: employees log in once and their agent connections are authenticated automatically
- Token scoping: different agents can have different permission levels based on IdP roles

## API Key (Development)

For local development and testing. Not recommended for production.

### Usage

```
wss://your-relay.example/ws/bridge?key=<api-key>
```

API keys are issued by the relay operator. They are scoped to a developer account and inherit that account's tier limits.

### Limitations

- API keys do not support E2EE (no key exchange handshake)
- API keys are visible in connection logs and URL parameters
- API keys should be rotated regularly
- For production, always use bridge pairing tokens, OAuth 2.0 / OIDC, mTLS, or PSK

## mTLS

For headless, kiosk, fleet-deployed, and CAC/PIV-derived-credential scenarios where there is no interactive pairing flow. Both sides present X.509 certificates at the WebSocket TLS handshake; the relay validates the surface or agent against a configured trust anchor (typically a tenant CA or a smart-card-derived chain).

### Use Cases

- Defense, healthcare, regulated industrial deployments that already manage a PKI
- Fleet operators bootstrapping device credentials at manufacturing time
- Kiosks and embedded surfaces that have no interactive pairing UI
- CAC/PIV-derived credentials for personnel-bound surfaces

### Configuration

- Trust anchor: tenant CA, smart-card-issuing CA, or vendor PKI configured per relay account
- Certificate binding: the relay maps the presented certificate's identity (Subject DN, SAN, or vendor-specific extension) to a specific (agent, surface) tuple
- Renewal: handled by the issuing CA; the relay re-validates on each TLS session

### Requirements

- Implementations MUST validate the full certificate chain to a configured trust anchor.
- Implementations MUST reject connections whose presented certificate cannot be bound to a specific (agent, surface) tuple via the relay's identity mapping.
- Private keys MUST be stored using platform-appropriate hardware-backed storage (TPM, secure element, smart card, or HSM) where available.

## Pre-Shared Key (PSK)

For air-gapped deployments and environments where no online identity provider is available. A symmetric key is provisioned out of band to both the surface (or agent) and the relay; the credential is presented at connection time.

### Use Cases

- Closed deployments that need offline operation
- Bring-up and provisioning flows before mTLS or OAuth is configured
- Test environments isolated from production identity infrastructure

### Requirements

- PSK keys MUST be scoped to a specific (agent, surface) tuple at provisioning.
- Deployers MUST establish a key rotation schedule appropriate to their threat model.
- PSK material MUST be stored using platform-appropriate secure storage (see [Credential Storage](#credential-storage)).

## Credential Storage

All credential types are subject to platform-appropriate secure storage. Implementations SHOULD prefer hardware-backed storage where available.

| Platform | Recommended storage |
|----------|---------------------|
| Apple platforms (iOS, macOS) | Keychain (`kSecAttrAccessibleAfterFirstUnlock` or stricter) |
| Windows | Credential Manager (DPAPI-protected) |
| Linux (desktop) | Secret Service (GNOME Keyring, KWallet) |
| Linux (server) | Deployment-specific; common patterns include systemd-creds, HashiCorp Vault, Kubernetes Secrets with appropriate RBAC, and TPM-backed storage via tpm2-tss. Implementers SHOULD follow their organization's existing secrets management practice. |
| Android | Android Keystore |
| Embedded / IoT | TPM, secure element, or vendor-provided secure storage |
| Fleet / industrial | HSM, TPM, or vendor-provided secure storage |

Production credentials MUST NOT be stored in plaintext configuration files. Development credentials (e.g., API keys for local testing) are exempt from the hardware-backed-storage SHOULD but MUST NOT be committed to version control.

## End-to-End Encryption (E2EE)

E2EE is an optional layer that encrypts message content so the relay cannot read it.

### Key Exchange (ECDH P-256)

1. Both agent and surface generate ephemeral P-256 key pairs
2. Public keys are exchanged during connection handshake:
   - Agent includes public key in Agent Card
   - Surface includes public key in a `key_exchange` message
3. Both sides compute shared secret via ECDH
4. Shared secret derives AES-256-GCM encryption keys via HKDF

### Encrypted Message Format

```json
{
  "type": "chat_stream_chunk",
  "id": "uuid",
  "encrypted_payload": "base64(iv + ciphertext + tag)",
  "e2ee": true
}
```

- `type` and `id` remain plaintext (relay needs type for routing)
- All other fields are encrypted into `encrypted_payload`
- Each message uses a unique 96-bit IV
- AES-256-GCM authentication tag appended to ciphertext

### What the Relay Sees

| With E2EE | Without E2EE |
|-----------|--------------|
| `type`: "chat_stream_chunk" | `type`: "chat_stream_chunk" |
| `id`: "uuid" | `id`: "uuid" |
| `encrypted_payload`: opaque blob | `delta`: "Hey there" |
| | `accumulated`: "Hey there, how are you?" |
| | `reply_to`: "message-uuid" |

### Implementation

The encryption module (`crypto-utils.js` in the reference bridge) provides:
- Key generation (P-256 ephemeral key pairs)
- Shared secret derivation (ECDH)
- Encrypt/decrypt with AES-256-GCM
- Convenience wrappers for relay message format
- Self-test verifying key generation, encryption, decryption, and tamper detection

## See Also

- [SPEC.md](../SPEC.md) — Sections 3.2 (Authentication), 7 (Authentication Methods), 8 (Encryption)
- [Architecture](./architecture.md) — Security model overview
