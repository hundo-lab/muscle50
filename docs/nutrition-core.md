# Nutrition Core

Nutrition Core is a pure, deterministic domain layer. A replaceable parser turns
free text into meal/item structure; it does not own nutrient calculations.
Repositories persist the resulting domain objects and append-only nutrition fact
history.

## Data flow

1. `MealParser` produces `ParsedMeal` / `ParsedMealItem` from the original text.
2. `materialize_parsed_meal` assigns a caller-supplied stable ID and retains the
   parser/model versions without creating any nutrient estimate.
3. Application code attaches product, label, database, or estimate facts.
4. For each nutrient independently, the domain selects the highest-priority active
   fact compatible with the item's quantity unit and scales it under a fixed
   28-digit, half-even `Decimal` context.
5. Meal/day aggregation exposes `totals` only when every item contributes that
   nutrient. `known_subtotals` remains available for partial data, and incomplete
   and estimated field sets prevent either value from being mistaken for exact.

Source priority is label, explicit user numeric value, known product, generic food
database, then estimates. Visual and language estimates share the same tier; stable
confidence/time/ID tie-breakers decide between them. A new fact may supersede an
old fact, but the old fact remains in history. Nutrients with different provenance
must be represented by separate facts; selection is performed per nutrient.

Meal items may retain a `food_profile_id` so a repository can resolve the same
known product again while still snapshotting the facts used for the historical
meal.

Unit equality is intentional: Nutrition Core never guesses that a pack, piece, or
animal equals a particular gram amount. A verified cross-unit conversion (for
example, `1 pack = 120 g`) needs a future conversion value object with its own
provenance before per-gram data can be applied to packs.

`nutrition_meal_v1.schema.json` is the versioned interchange schema. Decimal values
are strings to avoid binary floating-point drift. `src/muscle50/infrastructure/sqlite/nutrition_schema.sql`
is a feature-local schema, not a numbered migration; it is loaded directly by
`SqliteMealRepository`/`SqliteFoodNutritionRepository.migrate()`, not by
`database.py`. Integration must assign its final migration number after the
parallel branches are reconciled. Its DDL is idempotent (`CREATE TABLE IF NOT
EXISTS`, etc.) so it can be re-run safely, but that also means it cannot evolve
columns on a database that already has the tables — `migrate()` against an
older `nutrition_meals` succeeds silently and a later write then fails with
`OperationalError: no such column`; whoever assigns the migration number must
add explicit `ALTER TABLE`/backfill steps for any column change.
