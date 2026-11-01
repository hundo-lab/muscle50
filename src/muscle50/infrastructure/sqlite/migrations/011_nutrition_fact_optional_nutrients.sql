-- LDL Nutrients v1: optional nutrients (saturated fat, fiber) of a nutrition fact.
-- nutrition_facts (003) has fixed per-nutrient columns and is append-only; adding columns would need
-- ALTER, which the loader would re-run on every start. One row per (fact, nutrient) that has a value or
-- an estimate range; no row means unknown, never 0. Rows are written in their fact's transaction and are
-- append-only like the fact. No existing table is altered; no other migration's table is referenced.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS nutrition_fact_optional_nutrients (
    fact_id TEXT NOT NULL REFERENCES nutrition_facts(fact_id) ON DELETE RESTRICT,
    nutrient TEXT NOT NULL CHECK (nutrient IN ('saturated_fat_g', 'fiber_g')),
    value TEXT,
    minimum TEXT,
    maximum TEXT,
    PRIMARY KEY (fact_id, nutrient),
    CHECK ((minimum IS NULL) = (maximum IS NULL)),
    CHECK (value IS NOT NULL OR minimum IS NOT NULL)
);

CREATE TRIGGER IF NOT EXISTS nutrition_fact_optional_nutrients_prevent_update
BEFORE UPDATE ON nutrition_fact_optional_nutrients
BEGIN
    SELECT RAISE(ABORT, 'nutrition fact optional nutrients are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_fact_optional_nutrients_prevent_delete
BEFORE DELETE ON nutrition_fact_optional_nutrients
BEGIN
    SELECT RAISE(ABORT, 'nutrition fact optional nutrients are append-only');
END;

CREATE TRIGGER IF NOT EXISTS nutrition_fact_optional_nutrients_exact_has_no_range
BEFORE INSERT ON nutrition_fact_optional_nutrients
WHEN NEW.minimum IS NOT NULL
 AND (SELECT accuracy FROM nutrition_facts WHERE fact_id = NEW.fact_id) = 'exact'
BEGIN
    SELECT RAISE(ABORT, 'exact nutrition facts cannot carry an estimate range');
END;

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (11, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
