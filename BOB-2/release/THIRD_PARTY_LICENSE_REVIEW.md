# Third-Party License Review

**Release commit:** ____________________  
**Review date:** ____________________  
**Reviewer:** ____________________

## Current decision

The repository must not be marketed as a closed-source proprietary SaaS until every runtime dependency has a recorded license and all copyleft/commercial obligations are resolved.

### Material finding — PyMuPDF / MuPDF

The current dependency set includes `PyMuPDF==1.28.0`. PyMuPDF's official documentation states that PyMuPDF and MuPDF are dual-licensed under AGPL and commercial license agreements. Artifex states that server/SaaS use under the AGPL requires the applicable source-code disclosure obligations, and that a commercial license is required when those obligations cannot be met.

Approved resolution must be one of:

1. **Commercial license:** obtain written Artifex terms covering the intended SaaS/OEM use and retain the agreement reference below; or
2. **AGPL distribution:** obtain legal approval for the complete product and network-source-offer obligations; or
3. **Replacement:** remove PyMuPDF/MuPDF from runtime and replace it with dependencies whose licenses are approved for the selected commercial model, with regression tests for PDF validation, extraction, OCR and bank-statement parsing.

**Selected path:** ☐ Commercial license ☐ AGPL model ☐ Replacement  
**Agreement / legal opinion / replacement PR:** ____________________  
**Approved by:** ____________________  
**Date:** ____________________

Until one box is completed with evidence, status is **BLOCKED FOR CLOSED-SOURCE SALE**.

## Automated inventory requirements

For each release, generate and retain:

- Python direct and transitive package names, versions, license metadata and source URL;
- npm production package names, versions and license metadata;
- container base image and operating-system package inventory;
- SBOM in CycloneDX or SPDX format;
- vulnerability scan results;
- copies or links to required notices and license texts.

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
