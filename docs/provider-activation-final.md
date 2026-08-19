# Final provider activation wiring

- BatchData skip tracing uses the official BatchData property skip-trace endpoint by default; `BATCHDATA_SKIPTRACE_URL` remains an optional override.
- Google Maps / Street View is optional visual support and does not block core acquisition readiness.
- Bland remains the only active phone transport; SMS remains disabled.
- Contract execution and private document retention remain fail-closed until a real e-sign provider and secure object-storage provider are configured.
