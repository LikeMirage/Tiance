-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

ALTER TABLE provider_custom_models
ADD COLUMN price_currency TEXT NOT NULL DEFAULT 'CNY';

ALTER TABLE provider_custom_models
ADD COLUMN input_price_per_million REAL;

ALTER TABLE provider_custom_models
ADD COLUMN output_price_per_million REAL;
