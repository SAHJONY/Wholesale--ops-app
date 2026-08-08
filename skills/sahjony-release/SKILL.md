---
name: sahjony-release
version: "1.0.0"
description: "Controlled release gate for SAHJONY Wholesale OS."
user-invocable: true
---
# SAHJONY Release
Block release unless targeted tests pass, high-risk regression passes, migrations have one head, app imports/builds, tenant-isolation and approval-boundary tests pass, secrets/config checks are non-destructive, frontend/backend route contract passes, deployed revision can be reported, and rollback is documented. This skill reviews readiness only; commit, push, PR, merge, deployment, outreach, contracts, and financial actions remain separately authorized.
