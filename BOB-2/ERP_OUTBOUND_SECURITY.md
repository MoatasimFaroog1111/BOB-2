# ERP/Odoo outbound SSRF and egress security

This policy applies to every tenant-configurable Odoo connection, including connection tests, discovery, reads, journal posting, Telegram-originated posting, and attachment creation.

## Production posture

Production is fail-closed. Set an explicit destination policy before deploying:

```env
ERP_OUTBOUND_REQUIRE_ALLOWLIST=true
ERP_OUTBOUND_ALLOWED_HOSTS=odoo.company.example
ERP_OUTBOUND_ALLOWED_CIDRS=
ERP_OUTBOUND_ALLOWED_PORTS=443
ERP_OUTBOUND_ALLOW_HTTP=false
ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS=10
ERP_OUTBOUND_READ_TIMEOUT_SECONDS=30
ERP_OUTBOUND_MAX_RESPONSE_BYTES=10485760
```

`ERP_OUTBOUND_ALLOWED_HOSTS` accepts exact hostnames and controlled subdomain patterns such as `*.odoo.company.example`. A global `*` is forbidden. The apex domain is not matched by a subdomain wildcard.

## Public Odoo destination

For an Internet-routable Odoo service:

1. Add the exact hostname to `ERP_OUTBOUND_ALLOWED_HOSTS`.
2. Keep `ERP_OUTBOUND_ALLOWED_CIDRS` empty.
3. Keep HTTPS enforced.
4. Add only the actual TLS port to `ERP_OUTBOUND_ALLOWED_PORTS`.
5. Ensure the hostname resolves only to globally routable addresses.

Every DNS answer is evaluated. A hostname that returns one public address and one private or special-use address is rejected entirely.

## Private or on-premises Odoo destination

Private connectivity requires two independent approvals:

1. the exact hostname must be in `ERP_OUTBOUND_ALLOWED_HOSTS`; and
2. the resolved private address must fall inside a narrow network in `ERP_OUTBOUND_ALLOWED_CIDRS`.

Example:

```env
ERP_OUTBOUND_ALLOWED_HOSTS=odoo.internal.company.example
ERP_OUTBOUND_ALLOWED_CIDRS=10.42.18.0/24
ERP_OUTBOUND_ALLOWED_PORTS=443
```

Only subnets of RFC1918, IPv6 ULA, or explicitly supported CGNAT space are accepted. Do not use broad ranges such as `0.0.0.0/0`, `10.0.0.0/8` when a narrower subnet is available, or link-local ranges.

## Addresses that are always denied

The following classes are denied even if a hostname is allowlisted:

- IPv4 and IPv6 loopback;
- link-local addresses;
- unspecified, multicast, and reserved addresses;
- cloud metadata and platform virtual IPs;
- IPv4-mapped IPv6 forms of denied IPv4 addresses;
- private addresses outside the configured CIDRs;
- non-global special-use addresses.

This blocks common targets such as `127.0.0.1`, `::1`, `169.254.169.254`, container metadata endpoints, and internal services that were not explicitly approved.

## URL restrictions

ERP base URLs must:

- use `https` unless HTTP is explicitly enabled outside production;
- contain no username or password;
- contain no query string or fragment;
- use an allowed port;
- contain no encoded path components, backslashes, duplicate separators, or `.`/`..` traversal;
- match the configured hostname allowlist.

Credentials belong in the encrypted ERP secret record, never in the URL.

## DNS rebinding protection

Validation is not separated from connection establishment:

1. the application resolves the allowlisted hostname;
2. every returned address is validated;
3. the XML-RPC transport opens the socket directly to one of those validated addresses;
4. TLS still verifies the certificate against the original hostname;
5. the Host header and SNI retain the original hostname;
6. the policy is reevaluated for every new XML-RPC connection.

The transport does not use an unpinned default `xmlrpc.client.ServerProxy` connection and does not permit proxy tunnels.

## Resource and redirect controls

- connect and read timeouts are independently bounded;
- XML-RPC response bytes are counted after gzip decoding;
- oversized declared or streamed responses are rejected;
- HTTP redirect handling is not enabled by the XML-RPC transport;
- a mismatched host supplied to the transport is rejected;
- raw destination IPs and credentials must not be logged or returned to clients.

## Deployment procedure

Before deploying this stage:

1. Inventory every active row in `erp_connections`.
2. Normalize the expected Odoo hostnames and ports.
3. Populate `ERP_OUTBOUND_ALLOWED_HOSTS` with only those destinations.
4. Add narrow private CIDRs only when required.
5. Verify the Odoo TLS certificate matches its hostname.
6. Deploy with `ERP_OUTBOUND_ALLOW_HTTP=false`.
7. Run the saved-connection test for each tenant.
8. Review audit and application logs for outbound-policy denials without exposing credentials.

Existing saved connections are revalidated on every use. A previously saved destination does not bypass the new policy.

## Required CI gates

The dedicated regression suite is:

```text
backend/tests/test_erp_outbound_security.py
```

CI must fail if:

- the Odoo provider returns to a default unpinned `ServerProxy`;
- hostname or CIDR allowlisting disappears;
- metadata, loopback, private-address, or mixed-DNS rejection disappears;
- DNS pinning or TLS hostname verification disappears;
- proxy tunnels become available;
- connect/read timeouts or the response-size ceiling disappear;
- production Compose permits HTTP or omits the ERP hostname allowlist.

This stage does not approve external LLM data transfer or replace application secrets with a centralized secret store. Those controls remain separate production gates.
