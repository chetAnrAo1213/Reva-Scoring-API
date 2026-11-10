
from datetime import datetime, timezone
from typing import Any


MODEL_VERSION = "dynamic_category_v1"

HALF_LIFE_SECONDS = 14 * 24 * 60 * 60

WATCH_MAX_STRENGTH = 0.50
LIKE_STRENGTH = 0.65
REPOST_STRENGTH = 0.80

MIN_WEIGHT = -1.0
MAX_WEIGHT = 1.0


def normalize_folder(folder: str) -> str:
    return " ".join(
        str(folder).strip().lower().split()
    )


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value

    elif isinstance(value, (int, float)):
        result = datetime.fromtimestamp(
            value,
            tz=timezone.utc
        )

    elif isinstance(value, str):
        result = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

    else:
        raise ValueError("Invalid event timestamp.")

    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)

    return result.astimezone(timezone.utc)


def timestamp_seconds(value: Any) -> float:
    return parse_timestamp(value).timestamp()


def clamp(value: float) -> float:
    return max(
        MIN_WEIGHT,
        min(MAX_WEIGHT, value)
    )


def initial_state(categories: list[str]) -> dict:
    return {
        "categories": {
            category: {
                "weight": 0.0,
                "positiveEvents": 0,
                "negativeEvents": 0
            }
            for category in categories
        },
        # Internal decay reference; persisted as lastScoredAt
        # inside profileScores, not scoringMetadata.
        "lastTimestamp": None
    }


def apply_decay(
    state: dict,
    current_timestamp: float
) -> None:

    last_timestamp = state.get("lastTimestamp")

    if last_timestamp is None:
        return

    elapsed = current_timestamp - last_timestamp

    if elapsed <= 0:
        return

    decay_factor = 0.5 ** (
        elapsed / HALF_LIFE_SECONDS
    )

    for category_data in state["categories"].values():
        category_data["weight"] = clamp(
            category_data["weight"] * decay_factor
        )


def calculate_event_signal(event: dict) -> float | None:
    event_type = event.get("eventType")

    if event_type == "VIDEO_LIKED":
        return LIKE_STRENGTH

    if event_type == "VIDEO_REPOSTED":
        return REPOST_STRENGTH

    if event_type == "VIDEO_WATCHED":

        watched_duration = float(
            event.get("watchDurationSeconds", 0)
        )

        video = event.get("video") or {}

        actual_duration = float(
            video.get("duration", 0)
        )

        if actual_duration <= 0:
            raise ValueError(
                "Video duration must be greater than zero."
            )

        if watched_duration < 0:
            raise ValueError(
                "Watch duration cannot be negative."
            )

        watch_ratio = min(
            watched_duration / actual_duration,
            1.0
        )

        return (
            (2.0 * watch_ratio - 1.0)
            * WATCH_MAX_STRENGTH
        )

    return None


def update_weight(
    current_weight: float,
    signal: float
) -> float:

    if signal >= 0:
        updated_weight = current_weight + (
            (1.0 - current_weight) * signal
        )

    else:
        updated_weight = current_weight + (
            (-1.0 - current_weight) * abs(signal)
        )

    return clamp(updated_weight)


def score_events(
    events: list[dict],
    categories: list[str],
    state: dict | None = None,
    as_of_timestamp: datetime | None = None
) -> dict:

    if state is None:
        state = initial_state(categories)

    # Keep only currently active categories.
    existing_categories = state.get(
        "categories",
        {}
    )

    state["categories"] = {
        category: existing_categories.get(
            category,
            {
                "weight": 0.0,
                "positiveEvents": 0,
                "negativeEvents": 0
            }
        )
        for category in categories
    }

    # Match folder names without case sensitivity.
    category_lookup = {
        normalize_folder(category): category
        for category in categories
    }

    # Process events chronologically within this batch.
    sorted_events = sorted(
        events,
        key=lambda event: timestamp_seconds(
            event["timestamp"]
        )
    )

    summary = {
        "processed": 0,
        "skipped": 0,
        "unknownCategories": [],
        "ignoredEventTypes": 0
    }

    for event in sorted_events:

        timestamp = parse_timestamp(
            event["timestamp"]
        )

        current_timestamp = timestamp.timestamp()

        folder = (
            event.get("video") or {}
        ).get("folder")

        if not folder:
            raise ValueError(
                "Video folder is missing from the event."
            )

        category = category_lookup.get(
            normalize_folder(folder)
        )

        if category is None:

            if folder not in summary["unknownCategories"]:
                summary["unknownCategories"].append(folder)

            summary["skipped"] += 1
            continue

        signal = calculate_event_signal(event)

        if signal is None:
            summary["ignoredEventTypes"] += 1
            continue

        last_timestamp = state.get("lastTimestamp")

        # Apply decay when time moves forward.
        # Older events are still counted; they are not rejected.
        if (
            last_timestamp is None
            or current_timestamp > last_timestamp
        ):
            apply_decay(
                state,
                current_timestamp
            )

        category_data = state["categories"][category]

        category_data["weight"] = update_weight(
            category_data["weight"],
            signal
        )

        if signal >= 0:
            category_data["positiveEvents"] += 1
        else:
            category_data["negativeEvents"] += 1

        # Keep the latest timestamp as the decay reference.
        state["lastTimestamp"] = max(
            state.get("lastTimestamp") or 0,
            current_timestamp
        )

        summary["processed"] += 1

    # Apply decay to the current time when returning scores.
    if as_of_timestamp is not None:

        current_time = parse_timestamp(
            as_of_timestamp
        ).timestamp()

        apply_decay(
            state,
            current_time
        )

        state["lastTimestamp"] = max(
            state.get("lastTimestamp") or 0,
            current_time
        )

    scores = [
        {
            "category": category,
            "weight": round(
                data["weight"],
                6
            ),
            "positiveEvents": data["positiveEvents"],
            "negativeEvents": data["negativeEvents"]
        }
        for category, data in state["categories"].items()
    ]

    scores.sort(
        key=lambda item: item["weight"],
        reverse=True
    )

    return {
        "modelVersion": MODEL_VERSION,
        "scores": scores,
        "state": state,
        "summary": summary
    }
