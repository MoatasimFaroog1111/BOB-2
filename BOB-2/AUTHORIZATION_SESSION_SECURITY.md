# Live Role Authorization and Session Revocation

## Authorization source of truth

The role stored in an access JWT is retained only for client compatibility. It is never authoritative on the server.

For every protected request, the backend:

1. validates the signed access token;
2. requires a server-side `AuthSession` matching both `sid` and `jti`;
3. loads the current `User` from the database;
4. verifies that the user and organization are active;
5. verifies that the token, session, and user have the same `security_version`;
6. replaces the JWT role and organization values with the current database values;
7. evaluates RBAC permissions using that current database role.

A signed token without a valid server-side session is rejected in every environment.

## Security-sensitive user changes

The following ORM changes increment `users.security_version` and revoke every active session for the user in the same database transaction:

- role;
- password hash;
- active/inactive status;
- organization assignment;
- email identity.

Disabling an organization revokes active sessions belonging to all users assigned to that organization. Login and refresh also fail closed when the organization is missing or inactive.

## Token and session binding

New access and refresh tokens contain an `sv` claim. Each `auth_sessions` row stores:

- `organization_id`;
- `user_security_version`;
- `revoked_at`;
- a non-secret `revocation_reason`.

The refresh endpoint rechecks all current user and organization state before issuing a replacement token. Atomic refresh-token rotation is handled separately by the refresh-race remediation stage.

## Password changes

`POST /api/v1/auth/change-password` requires the current authenticated session, verifies the existing password, applies the password-strength policy, and changes the password through the same model path that increments the security version. The current session and all other sessions are therefore unusable immediately after the response.

No password, token, hash, or session secret is written to audit details.

## Migration behavior

Migration `f3a9d2c7b410` adds the security-version and tenant-binding fields. Every session created before this migration is revoked with reason `security_version_migration`, because those tokens do not contain an `sv` claim.

Sessions that cannot be tied to a valid organization-bound user are deleted during migration. Users must sign in again after the migration is applied.

## Operational boundary

Merging the code does not prove that the migration has been applied to the live database or that the backend service has deployed the merged commit. Production verification must confirm both before this control is considered active in the live environment.
