# Railway ClamAV production release gate

This gate must be completed before merging the branch that removes Railway's temporary malware-scanning startup exceptions.

## Target architecture

- Deploy a dedicated Railway service named `clamav` from the public image `clamav/clamav:stable`.
- Keep the service private. Do not create a public domain or expose TCP/3310 to the Internet.
- Attach a volume at `/var/lib/clamav` so signature databases survive redeployments.
- The backend reaches the scanner through Railway private networking at `clamav.railway.internal:3310`.

## Backend variables

Set these variables on the production backend service:

```env
REQUIRE_MALWARE_SCAN=true
CLAMAV_HOST=clamav.railway.internal
CLAMAV_PORT=3310
```

Apply the variable changes only after the ClamAV deployment is running. Redeploy the backend after all three values are present.

## Required validation evidence

Capture the deployment IDs, timestamps, and sanitized results for each check:

1. ClamAV service reaches a successful running state and has no public domain.
2. The backend redeploys successfully with the mandatory variables above.
3. `GET /health` returns HTTP 200 after the backend redeploy.
4. A normal supported document passes upload validation.
5. An EICAR test payload is rejected with a malware-scanner validation error.
6. Stopping or making ClamAV unreachable causes uploads to fail closed with `Malware scan could not be completed` while `REQUIRE_MALWARE_SCAN=true`.
7. Restoring ClamAV returns clean uploads to normal operation.
8. Production logs and audit records contain no document contents, credentials, or scanner connection secrets.

Use only an isolated test tenant and non-financial sample files. Do not use customer documents or post any accounting entry during this validation.

## Safe deployment order

1. Deploy the private `clamav` service and wait for its signature database initialization to finish.
2. Confirm TCP/3310 is reachable from the backend's Railway private network.
3. Set `CLAMAV_HOST`, `CLAMAV_PORT`, and `REQUIRE_MALWARE_SCAN` on the backend.
4. Redeploy the backend and verify `/health`.
5. Run clean-file, EICAR, and scanner-unavailable tests.
6. Save sanitized evidence in the release record.
7. Merge the fail-closed application PR only after all checks above pass.

## Rollback

If the backend cannot start after enforcing the gate, roll back the backend to the previous successful deployment while keeping the ClamAV service private. Do not weaken `REQUIRE_MALWARE_SCAN` in a release that accepts production uploads. Investigate the private DNS name, port, scanner readiness, and Railway service health before retrying.
