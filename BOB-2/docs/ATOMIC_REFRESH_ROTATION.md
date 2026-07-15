# Atomic Refresh-Token Rotation

## Security contract

Every refresh token is bound to four server-verified values:

- session ID (`sid`)
- token family ID (`fid`)
- user security version (`sv`)
- monotonic rotation generation (`rgn`)

The current refresh JTI and SHA-256 token hash remain in `auth_sessions`. The monotonic generation is stored separately in `auth_session_rotation_states`.

A refresh request obtains a row lock where the database supports `SELECT ... FOR UPDATE`, then performs a compare-and-swap update that succeeds only when the stored generation still equals the generation presented by the token. The session JTI and token hash are replaced in the same transaction.

## Concurrent requests

When two requests present the same refresh token concurrently:

1. both may pass signature validation;
2. only one compare-and-swap may advance the generation;
3. the other request is treated as replay;
4. the complete token family is revoked;
5. the already returned winner token is therefore unusable after replay detection.

This strict policy avoids creating two valid descendant refresh tokens. Clients must serialize refresh operations and must not retry the same refresh token after an ambiguous network result.

## Replay and device changes

Reuse of an old generation, JTI, or token hash revokes the token family. A changed User-Agent also revokes the family. Responses remain generic HTTP 401 messages and do not disclose which check failed.

## Security event history

`auth_session_security_events` stores non-secret events such as:

- `session_created`
- `refresh_rotated`
- `refresh_replay_detected`
- `concurrent_refresh_replay`
- `refresh_device_changed`
- `user_logout`
- `atomic_rotation_migration`

The event writer removes metadata keys containing token, JTI, hash, password, secret, or credential. User-Agent values are represented only by SHA-256 fingerprints.

## Migration

Migration `a8c4e1f2d670` creates rotation state and event tables, backfills generation zero, and revokes all sessions created before atomic rotation with reason `atomic_rotation_migration`.

Applying the migration intentionally signs every currently authenticated user out once. Deploy the backend code and migration together. Do not run the new code against the old schema or the old code against the new session policy.

## Operational checks

After deployment:

1. confirm the Alembic head is `a8c4e1f2d670`;
2. confirm new logins create one generation-zero state and one `session_created` event;
3. confirm a normal refresh advances generation to one;
4. confirm replaying the old token returns 401 and revokes the family;
5. monitor replay and device-change event rates without logging token material.

Telegram and external LLM production execution remain disabled independently of this authentication change.
