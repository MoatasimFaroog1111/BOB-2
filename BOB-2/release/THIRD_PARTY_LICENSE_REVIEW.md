# Third-Party License Review

**Release commit:** ____________________  
**Review date:** ____________________  
**Reviewer:** ____________________

## Current decision

The repository must not be marketed as a closed-source proprietary SaaS until every runtime dependency has a recorded license and all copyleft/commercial obligations are resolved.

### Resolved finding — PyMuPDF / MuPDF removed

The former `PyMuPDF` / MuPDF runtime dependency was replaced with `pypdf`, `pdfplumber`, and `pypdfium2`. The current Python dependency manifests do not contain `PyMuPDF`, and application source files do not import `fitz`.

**Selected path:** ☒ Replacement

**Implementation evidence:** `backend/scripts/remove_pymupdf_dependency.py`, the current dependency manifests, and `backend/tests/test_pdf_replacement_regressions.py`

**Testing status:** Dedicated regression coverage verifies pypdf text extraction, encrypted-PDF rejection, rendered-page OCR fallback with resource cleanup, and positional PDF bank-statement parsing.

**Commercial-license blocker from PyMuPDF:** RESOLVED IN CURRENT SOURCE

This resolution removes the identified PyMuPDF blocker only. It does not complete the full license review. A release-specific dependency inventory, SBOM, vulnerability scan, notice bundle, product-code ownership confirmation, and counsel review remain mandatory before marking the project `READY` below.

## Automated inventory requirements

For each release, generate and retain:

- Python direct and transitive package names, versions, license metadata and source URL;
- npm production package names, versions and license metadata;
- container base image and operating-system package inventory;
- SBOM in CycloneDX or SPDX format;
- vulnerability scan results;
- copies or links to required notices and license texts.

Current generated CycloneDX 1.6 inventories and scoped dependency vulnerability results:

- `release/sbom/backend-runtime.cdx.json` — direct packages declared in the lightweight production manifest (`requirements.runtime.txt`).
- `release/sbom/backend-full-lock.cdx.json` — all 98 pinned components represented in the full backend lock, including the optional ML/development stack.
- `release/sbom/frontend-production.cdx.json` — flattened npm production graph derived from `package-lock.json`, validated with no dangling component references.
- `release/security/backend-pip-audit.json` — 0 known vulnerabilities in `requirements.runtime.txt` at generation time.
- `release/security/backend-full-lock-pip-audit.json` — all 96 auditable pinned packages in `requirements.lock`, including `sentence-transformers` and `transformers`; 0 known vulnerabilities at generation time.
- `release/security/frontend-npm-audit.json` — 0 known npm production dependency vulnerabilities at generation time.

The lock-based Python SBOM is a complete pinned-package inventory, not a license-approved dependency relationship graph. Container/OS inventory, image scanning, verified license metadata, notices, and manual license decisions remain incomplete. Results are time-bound and must be regenerated for each release.

## Policy classifications

| Classification | Default decision | Required action |
|---|---|---|
| MIT / BSD / Apache-2.0 / ISC | Usually acceptable | Retain notices and confirm no additional restrictions |
| MPL-2.0 / LGPL | Counsel review | Confirm linking/modification and distribution obligations |
| GPL / AGPL / SSPL / unknown custom license | Release blocker | Written legal/commercial resolution required |
| Proprietary/commercial | Release blocker until evidence | Retain executed license and scope |
| Missing/unknown metadata | Manual review | Inspect upstream source/distribution license |

## Product-owned code

Before distribution, the Provider must confirm:

- all contributors assigned or licensed their work to the Provider;
- no customer confidential code/data is included;
- branding, images, templates and fonts have commercial rights;
- the repository has an approved top-level license matching the selected business model;
- customer contracts do not promise rights broader than the Provider owns.

## Final status

- Automated inventory: ☐ Complete ☐ Incomplete
- Copyleft/commercial findings resolved: ☐ Yes ☐ No
- Top-level project license approved: ☐ Yes ☐ No
- Counsel approval reference: ____________________

**License audit status:** ☐ READY ☐ BLOCKED
