# Property Intelligence Map + TinyFish

## Purpose

This module adds an authenticated, workspace-scoped property intelligence radar inspired by the modular geospatial patterns in God's Eye View. It does not import that project's live aircraft, CCTV, military, media, or third-party datasets.

The radar displays only SAHJONY single-family property records already linked to the active workspace. Texas and non-SFR records are excluded by the backend. Seller names, contact data, and owner identities are not included in the map payload.

## Routes

- `GET /property-intelligence/globe` — redacted property points, distress prioritization and deal economics.
- `GET /tinyfish/status` — configuration readiness without exposing the API key.
- `POST /tinyfish/research` — manager-only, allowlisted official-source research preview.
- `/owner/property-map` — owner-facing radar and TinyFish research console.

## TinyFish configuration

Set these variables only in the backend environment:

```env
TINYFISH_API_KEY=sk-tinyfish-...
TINYFISH_ALLOWED_DOMAINS=escambiaclerk.com,escambiataxcollector.com,pa.escambia.fl.us
```

`TINYFISH_ALLOWED_DOMAINS` is mandatory. A source URL must use HTTPS, contain no embedded credentials, target a hostname rather than an IP address, and match an allowlisted domain or subdomain.

Start with official assessor, recorder, tax collector, clerk/court docket, code enforcement, auction, and permit domains whose automation terms have been reviewed. Do not add people-search sites, paywalled sources, social networks, or domains whose terms prohibit automated access.

## Verification boundary

TinyFish output is always returned as `unverified_automation_preview`. The integration:

- does not request phone numbers or email addresses;
- does not write property truth or authorize outreach;
- does not infer ownership or legal status from incomplete pages;
- limits court-docket extraction to high-level record facts and excludes minors, allegations and unrelated family details;
- requires comparison with an authoritative county source and human approval.

Contact enrichment remains a separate licensed workflow followed by identity matching, DNC/TCPA screening, quiet-hours enforcement and owner approval.

## Cost and reliability controls

- Keep TinyFish wallet auto-reload disabled during the pilot or set a conservative provider-side limit.
- Start with two counties and at most 100 property research previews.
- Track completion rate, source conflicts, median steps, cost per accepted record and manual review time.
- Never represent a configured API key as operational readiness until a permitted source succeeds and its result is reviewed.

## Commercial data boundary

God's Eye View source code is MIT-licensed, but several bundled or live datasets have separate commercial restrictions. This integration reuses only the architectural idea of modular map layers and does not copy or deploy those datasets. Any future imagery or tile provider must receive its own terms, attribution, quota and cost review.
