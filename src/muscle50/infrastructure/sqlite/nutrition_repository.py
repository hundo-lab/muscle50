"""SQLite-backed MealRepository and FoodNutritionRepository implementations."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

from muscle50.domain.nutrition import (
    Accuracy,
    FoodNutritionProfile,
    Meal,
    MealItem,
    MealType,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionRange,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.decimal_text import decimal_from_text, decimal_to_text

_FACT_INSERT_SQL = """
INSERT INTO nutrition_facts (
    fact_id, meal_id, item_sequence, profile_id,
    calories_kcal, protein_g, carbohydrate_g, fat_g,
    min_calories_kcal, max_calories_kcal,
    min_protein_g, max_protein_g,
    min_carbohydrate_g, max_carbohydrate_g,
    min_fat_g, max_fat_g,
    basis_quantity, basis_unit,
    source_type, source_reference, confidence, accuracy,
    parser_version, model_version, created_at, supersedes_fact_id
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class SqliteMealRepository:
    """SQLite-backed MealRepository.

    ``save`` only creates a brand-new meal: calling it again with an already
    persisted ``meal_id`` is rejected rather than attempting to reconcile item
    or fact state, because nutrition_facts rows must never be mutated or
    dropped. Use ``append_nutrition_fact`` to add facts to a saved meal.

    Any item's ``food_profile_id`` must already exist in nutrition_food_profiles
    (insert the profile via SqliteFoodNutritionRepository first); otherwise
    ``save`` raises a raw ``sqlite3.IntegrityError`` from the foreign key.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def migrate(self) -> None:
        with _connect(self._database_path) as connection:
            connection.executescript(_load_schema_sql())

    def save(self, meal: Meal) -> None:
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM nutrition_meals WHERE meal_id = ?", (meal.meal_id,)
            ).fetchone()
            if existing is not None:
                raise ValueError(f"meal {meal.meal_id!r} already exists; use append_nutrition_fact to add facts")
            connection.execute(
                """
                INSERT INTO nutrition_meals (
                    meal_id, eaten_at, eaten_at_utc_sort_key, meal_type, original_text,
                    parser_version, model_version, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meal.meal_id,
                    meal.eaten_at.isoformat(),
                    _utc_sort_key(meal.eaten_at),
                    meal.meal_type.value,
                    meal.original_text,
                    meal.parser_version,
                    meal.model_version,
                    meal.notes,
                ),
            )
            for item in meal.items:
                connection.execute(
                    """
                    INSERT INTO nutrition_meal_items (
                        meal_id, item_sequence, food_name, food_profile_id,
                        quantity, quantity_unit, serving_description
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.meal_id,
                        item.sequence,
                        item.food_name,
                        item.food_profile_id,
                        decimal_to_text(item.quantity) if item.quantity is not None else None,
                        item.quantity_unit.value if item.quantity_unit is not None else None,
                        item.serving_description,
                    ),
                )
                _insert_facts_in_dependency_order(
                    connection,
                    item.nutrition_facts,
                    meal_id=item.meal_id,
                    item_sequence=item.sequence,
                    profile_id=None,
                )

    def get(self, meal_id: str) -> Meal | None:
        with _connect(self._database_path) as connection:
            return _load_meal(connection, meal_id)

    def list_eaten_between(self, start_inclusive: datetime, end_exclusive: datetime) -> tuple[Meal, ...]:
        _require_aware(start_inclusive, "start_inclusive")
        _require_aware(end_exclusive, "end_exclusive")
        start_key = _utc_sort_key(start_inclusive)
        end_key = _utc_sort_key(end_exclusive)
        with _connect(self._database_path) as connection:
            meal_ids = [
                row["meal_id"]
                for row in connection.execute(
                    """
                    SELECT meal_id FROM nutrition_meals
                    WHERE eaten_at_utc_sort_key >= ? AND eaten_at_utc_sort_key < ?
                    ORDER BY eaten_at_utc_sort_key, meal_id
                    """,
                    (start_key, end_key),
                ).fetchall()
            ]
            meals: list[Meal] = []
            for meal_id in meal_ids:
                meal = _load_meal(connection, meal_id)
                if meal is None:
                    raise RuntimeError(f"meal {meal_id!r} disappeared during listing")
                meals.append(meal)
        return tuple(meals)

    def append_nutrition_fact(self, meal_id: str, item_sequence: int, fact: NutritionFact) -> Meal:
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            item_row = connection.execute(
                "SELECT 1 FROM nutrition_meal_items WHERE meal_id = ? AND item_sequence = ?",
                (meal_id, item_sequence),
            ).fetchone()
            if item_row is None:
                raise ValueError(f"no meal item {meal_id!r}/{item_sequence} to attach a nutrition fact to")
            connection.execute(
                _FACT_INSERT_SQL,
                _fact_insert_row(fact, meal_id=meal_id, item_sequence=item_sequence, profile_id=None),
            )
            meal = _load_meal(connection, meal_id)
        if meal is None:
            raise RuntimeError(f"meal {meal_id!r} disappeared after appending a nutrition fact")
        return meal


class SqliteFoodNutritionRepository:
    """SQLite-backed FoodNutritionRepository.

    ``save`` only creates a brand-new profile: calling it again with an
    already persisted ``profile_id`` is rejected for the same append-only
    reasons as ``SqliteMealRepository.save``. Use ``append_nutrition_fact``
    to add facts to a saved profile.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def migrate(self) -> None:
        with _connect(self._database_path) as connection:
            connection.executescript(_load_schema_sql())

    def save(self, profile: FoodNutritionProfile) -> None:
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM nutrition_food_profiles WHERE profile_id = ?", (profile.profile_id,)
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    f"food profile {profile.profile_id!r} already exists; use append_nutrition_fact to add facts"
                )
            connection.execute(
                "INSERT INTO nutrition_food_profiles (profile_id, name) VALUES (?, ?)",
                (profile.profile_id, profile.name),
            )
            for alias in profile.aliases:
                connection.execute(
                    "INSERT INTO nutrition_food_profile_aliases (profile_id, alias) VALUES (?, ?)",
                    (profile.profile_id, alias),
                )
            _insert_facts_in_dependency_order(
                connection, profile.facts, meal_id=None, item_sequence=None, profile_id=profile.profile_id
            )

    def get(self, profile_id: str) -> FoodNutritionProfile | None:
        with _connect(self._database_path) as connection:
            return _load_profile(connection, profile_id)

    def search(self, name_or_alias: str) -> tuple[FoodNutritionProfile, ...]:
        """Case-insensitive exact match against the profile name or any of its aliases."""
        with _connect(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT p.profile_id FROM nutrition_food_profiles p
                LEFT JOIN nutrition_food_profile_aliases a ON a.profile_id = p.profile_id
                WHERE LOWER(p.name) = LOWER(?) OR LOWER(a.alias) = LOWER(?)
                ORDER BY p.profile_id
                """,
                (name_or_alias, name_or_alias),
            ).fetchall()
            profiles: list[FoodNutritionProfile] = []
            for row in rows:
                profile = _load_profile(connection, row["profile_id"])
                if profile is None:
                    raise RuntimeError(f"food profile {row['profile_id']!r} disappeared during search")
                profiles.append(profile)
        return tuple(profiles)

    def append_nutrition_fact(self, profile_id: str, fact: NutritionFact) -> FoodNutritionProfile:
        with _connect(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM nutrition_food_profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
            if existing is None:
                raise ValueError(f"no food profile {profile_id!r} to attach a nutrition fact to")
            connection.execute(
                _FACT_INSERT_SQL,
                _fact_insert_row(fact, meal_id=None, item_sequence=None, profile_id=profile_id),
            )
            profile = _load_profile(connection, profile_id)
        if profile is None:
            raise RuntimeError(f"food profile {profile_id!r} disappeared after appending a nutrition fact")
        return profile


def _load_schema_sql() -> str:
    return files("muscle50.infrastructure.sqlite").joinpath("nutrition_schema.sql").read_text(encoding="utf-8")


def _load_meal(connection: sqlite3.Connection, meal_id: str) -> Meal | None:
    meal_row = connection.execute("SELECT * FROM nutrition_meals WHERE meal_id = ?", (meal_id,)).fetchone()
    if meal_row is None:
        return None
    item_rows = connection.execute(
        "SELECT * FROM nutrition_meal_items WHERE meal_id = ? ORDER BY item_sequence", (meal_id,)
    ).fetchall()
    fact_rows = connection.execute(
        "SELECT * FROM nutrition_facts WHERE meal_id = ? ORDER BY item_sequence",
        (meal_id,),
    ).fetchall()
    facts_by_item: dict[int, list[NutritionFact]] = {}
    for fact_row in fact_rows:
        facts_by_item.setdefault(fact_row["item_sequence"], []).append(_fact_from_row(fact_row))
    # created_at is stored as ISO text with its original offset; sorting it as SQL text would
    # be wrong across differing offsets (the same trap eaten_at_utc_sort_key exists to avoid).
    # Sort the reconstructed aware datetimes instead, once the row count per item is tiny.
    for facts in facts_by_item.values():
        facts.sort(key=lambda fact: (fact.provenance.created_at, fact.fact_id))
    items = tuple(
        _item_from_row(item_row, tuple(facts_by_item.get(item_row["item_sequence"], ())))
        for item_row in item_rows
    )
    return Meal(
        meal_id=meal_row["meal_id"],
        eaten_at=datetime.fromisoformat(meal_row["eaten_at"]),
        meal_type=MealType(meal_row["meal_type"]),
        original_text=meal_row["original_text"],
        parser_version=meal_row["parser_version"],
        model_version=meal_row["model_version"],
        notes=meal_row["notes"],
        items=items,
    )


def _load_profile(connection: sqlite3.Connection, profile_id: str) -> FoodNutritionProfile | None:
    profile_row = connection.execute(
        "SELECT * FROM nutrition_food_profiles WHERE profile_id = ?", (profile_id,)
    ).fetchone()
    if profile_row is None:
        return None
    alias_rows = connection.execute(
        "SELECT alias FROM nutrition_food_profile_aliases WHERE profile_id = ? ORDER BY alias",
        (profile_id,),
    ).fetchall()
    fact_rows = connection.execute(
        "SELECT * FROM nutrition_facts WHERE profile_id = ?",
        (profile_id,),
    ).fetchall()
    # See the matching comment in _load_meal: created_at is offset-bearing ISO text, so it
    # must be sorted as reconstructed aware datetimes, not as raw SQL text.
    facts = sorted(
        (_fact_from_row(row) for row in fact_rows),
        key=lambda fact: (fact.provenance.created_at, fact.fact_id),
    )
    return FoodNutritionProfile(
        profile_id=profile_row["profile_id"],
        name=profile_row["name"],
        facts=tuple(facts),
        aliases=tuple(row["alias"] for row in alias_rows),
    )


def _item_from_row(row: sqlite3.Row, facts: tuple[NutritionFact, ...]) -> MealItem:
    return MealItem(
        meal_id=row["meal_id"],
        sequence=row["item_sequence"],
        food_name=row["food_name"],
        quantity=_optional_decimal(row["quantity"]),
        quantity_unit=QuantityUnit(row["quantity_unit"]) if row["quantity_unit"] is not None else None,
        food_profile_id=row["food_profile_id"],
        serving_description=row["serving_description"],
        nutrition_facts=facts,
    )


def _fact_insert_row(
    fact: NutritionFact,
    *,
    meal_id: str | None,
    item_sequence: int | None,
    profile_id: str | None,
) -> tuple[object, ...]:
    minimums: dict[str, Decimal] = {}
    maximums: dict[str, Decimal] = {}
    if fact.value_range is not None:
        for nutrient in NutrientField:
            bounds = fact.value_range.bounds(nutrient)
            if bounds is not None:
                minimums[nutrient.value], maximums[nutrient.value] = bounds

    def text(value: Decimal | None) -> str | None:
        return decimal_to_text(value) if value is not None else None

    return (
        fact.fact_id,
        meal_id,
        item_sequence,
        profile_id,
        text(fact.values.calories_kcal),
        text(fact.values.protein_g),
        text(fact.values.carbohydrate_g),
        text(fact.values.fat_g),
        text(minimums.get(NutrientField.CALORIES_KCAL.value)),
        text(maximums.get(NutrientField.CALORIES_KCAL.value)),
        text(minimums.get(NutrientField.PROTEIN_G.value)),
        text(maximums.get(NutrientField.PROTEIN_G.value)),
        text(minimums.get(NutrientField.CARBOHYDRATE_G.value)),
        text(maximums.get(NutrientField.CARBOHYDRATE_G.value)),
        text(minimums.get(NutrientField.FAT_G.value)),
        text(maximums.get(NutrientField.FAT_G.value)),
        decimal_to_text(fact.basis_quantity),
        fact.basis_unit.value,
        fact.provenance.source_type.value,
        fact.provenance.source_reference,
        text(fact.provenance.confidence),
        fact.provenance.accuracy.value,
        fact.provenance.parser_version,
        fact.provenance.model_version,
        fact.provenance.created_at.isoformat(),
        fact.supersedes_fact_id,
    )


def _fact_from_row(row: sqlite3.Row) -> NutritionFact:
    values = NutritionValue(
        calories_kcal=_optional_decimal(row["calories_kcal"]),
        protein_g=_optional_decimal(row["protein_g"]),
        carbohydrate_g=_optional_decimal(row["carbohydrate_g"]),
        fat_g=_optional_decimal(row["fat_g"]),
    )
    has_range = any(row[f"min_{nutrient.value}"] is not None for nutrient in NutrientField)
    value_range = (
        NutritionRange(
            minimum=NutritionValue(
                **{nutrient.value: _optional_decimal(row[f"min_{nutrient.value}"]) for nutrient in NutrientField}
            ),
            maximum=NutritionValue(
                **{nutrient.value: _optional_decimal(row[f"max_{nutrient.value}"]) for nutrient in NutrientField}
            ),
        )
        if has_range
        else None
    )
    return NutritionFact(
        fact_id=row["fact_id"],
        values=values,
        basis_quantity=decimal_from_text(row["basis_quantity"]),
        basis_unit=QuantityUnit(row["basis_unit"]),
        provenance=NutritionProvenance(
            source_type=NutritionSourceType(row["source_type"]),
            accuracy=Accuracy(row["accuracy"]),
            source_reference=row["source_reference"],
            created_at=datetime.fromisoformat(row["created_at"]),
            confidence=_optional_decimal(row["confidence"]),
            parser_version=row["parser_version"],
            model_version=row["model_version"],
        ),
        value_range=value_range,
        supersedes_fact_id=row["supersedes_fact_id"],
    )


def _insert_facts_in_dependency_order(
    connection: sqlite3.Connection,
    facts: tuple[NutritionFact, ...],
    *,
    meal_id: str | None,
    item_sequence: int | None,
    profile_id: str | None,
) -> None:
    """Insert facts so a superseding fact is never inserted before what it supersedes.

    The append-only trigger requires the superseded row to already exist, but
    callers (including tests) may attach facts to a Meal/Profile in any order.
    """
    remaining = list(facts)
    inserted: set[str] = set()
    while remaining:
        ready = [fact for fact in remaining if fact.supersedes_fact_id is None or fact.supersedes_fact_id in inserted]
        if not ready:
            raise ValueError("nutrition fact history has an unresolvable supersession reference")
        for fact in ready:
            connection.execute(
                _FACT_INSERT_SQL,
                _fact_insert_row(fact, meal_id=meal_id, item_sequence=item_sequence, profile_id=profile_id),
            )
            inserted.add(fact.fact_id)
        remaining = [fact for fact in remaining if fact.fact_id not in inserted]


def _optional_decimal(text: str | None) -> Decimal | None:
    return None if text is None else decimal_from_text(text)


def _utc_sort_key(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@contextmanager
def _connect(database_path: Path) -> Iterator[sqlite3.Connection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    _enable_wal(connection)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _enable_wal(connection: sqlite3.Connection) -> None:
    # Concurrent first starts can race while SQLite creates the database/WAL files.
    # Some Windows SQLite builds return SQLITE_BUSY here without honoring busy_timeout.
    for attempt in range(5):
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
