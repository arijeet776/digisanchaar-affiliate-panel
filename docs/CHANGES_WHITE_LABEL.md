# White-label build (DigiSanchaar)
- Logos replaced (public/quantix-logo-*.png keep their file names) and all visible "Quantix" text rebranded.
- Google Sheets / Apps Script backend removed completely (gas/, Apps Script tools, config, docs, tests).
  The shared storage layer was kept and renamed: storage/storage_adapter.py (BaseStorageAdapter), storage/finance_store.py,
  mongo_compat.AdapterDatabase, runtime.uses_adapter(). Supported STORAGE_BACKEND values: supabase_rest, mongodb_supabase.
- Click ids now start with `DGSNR` (was `QNCTX`); DB column `digisnr_click_id` (was `quantix_click_id`); migration file
  `001_schema.sql` (was `001_quantix_schema.sql`); webhook header `X-DigiSNR-Signature`; API keys start with `DGK_`.
  This build needs a FRESH Supabase database (column renamed) - do not run it against an old Quantix database.
