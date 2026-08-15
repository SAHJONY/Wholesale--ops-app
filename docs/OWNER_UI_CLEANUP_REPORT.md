# Owner UI cleanup report

This cleanup reduces the owner-facing application to the operating surfaces required by the current SAHJONY Wholesale OS.

## Removed pages

- root legacy `app/owner/national-intelligence/page.tsx`
- `frontend/app/owner/start/page.tsx`
- `frontend/app/owner/test-deal/page.tsx`
- `frontend/app/owner/go-live/page.tsx`
- `frontend/app/owner/launch-validation/page.tsx`
- `frontend/app/owner/activate/page.tsx`
- `frontend/app/owner/acquisition-automation/page.tsx`
- `frontend/app/owner/business/page.tsx`
- `frontend/app/owner/continuity/page.tsx`
- `frontend/app/owner/county/page.tsx`
- `frontend/app/owner/data-intake/page.tsx`
- `frontend/app/owner/events/page.tsx`
- `frontend/app/owner/intelligence/page.tsx`
- `frontend/app/owner/national-intelligence/page.tsx`
- `frontend/app/owner/nationwide-acquisition/page.tsx`
- `frontend/app/owner/nationwide-data/page.tsx`
- `frontend/app/owner/operations/page.tsx`
- `frontend/app/owner/real-estate-intelligence/page.tsx`

Total removed page files: 18.

## Navigation changes

The obsolete Advanced Tools navigation group was removed. The owner navigation now exposes only the canonical operating workflow, execution, intelligence, and system surfaces. SMS Acquisition remains available as `Campaigns` because it still contains unique campaign/scheduling/attribution controls.

## Preserved transitional routes

The cleanup intentionally does not remove `/owner/deals`, `/owner/public-data`, `/owner/provider-activation`, or `/owner/sessions` yet. Each still has either an active dependency or a unique control that must be migrated first.

## Safety

This cleanup removes UI pages only. Backend APIs, workers, data providers, audit controls, approval gates, and wholesale intelligence capabilities remain intact.
