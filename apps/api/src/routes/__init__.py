"""HTTP routes.

**Known gap, closed in Phase 8.** `docs/07-api.md` requires a Supabase JWT on
every endpoint except `/health`, forwarded to Postgres so row-level security
applies to the request itself. That is not built yet: Phase 2's read endpoints
connect as the owner role, which is exempt from RLS. The policies exist and are
proven (`tests/test_rls.py` runs as the non-owner `razormind_app` role), but
until Phase 8 they are not what stands between a caller and another tenant's
rows. `merchant_id` is a query parameter that *selects*; it does not yet
*enforce*.
"""
