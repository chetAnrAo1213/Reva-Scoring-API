
import json
import threading

from bson import ObjectId
from datetime import datetime, timezone
from collections import defaultdict

from Config.MongoConfig import users_collection

from Models.DynamicScoringModel import (
    MODEL_VERSION,
    initial_state,
    score_events,
    parse_timestamp
)

from Services.CategoryService import get_active_categories
from Services.VideoMetadataService import resolve_video_metadata


# Protects updates within this Python process.
_state_lock = threading.Lock()


def normalize_user_id(user_id) -> str:

    if isinstance(user_id, ObjectId):
        return str(user_id)

    if isinstance(user_id, dict):
        user_id = (
            user_id.get("$oid")
            or user_id.get("_id")
        )

    if user_id is None:
        raise ValueError("User ID is missing.")

    normalized = str(user_id).strip()

    if not normalized:
        raise ValueError("User ID is empty.")

    return normalized


def find_user_document(user_id: str):

    if not user_id:
        return None

    conditions = [
        {"_id": user_id}
    ]

    if ObjectId.is_valid(user_id):
        conditions.insert(
            0,
            {"_id": ObjectId(user_id)}
        )

    return users_collection.find_one({
        "$or": conditions
    })


def build_scoring_state(
    user: dict,
    categories: list[str]
) -> dict:

    state = initial_state(categories)

    profile_scores = (
        user.get("profileScores", {})
        .get(MODEL_VERSION, {})
    )

    saved_scores = profile_scores.get(
        "scores",
        {}
    )

    for category in categories:

        if category not in saved_scores:
            continue

        saved_data = saved_scores[category]

        if isinstance(saved_data, dict):

            state["categories"][category] = {
                "weight": float(
                    saved_data.get("weight", 0.0)
                ),
                "positiveEvents": int(
                    saved_data.get("positiveEvents", 0)
                ),
                "negativeEvents": int(
                    saved_data.get("negativeEvents", 0)
                )
            }

        else:

            # Compatibility with previously saved numeric scores.
            state["categories"][category]["weight"] = float(
                saved_data
            )

    # Read the decay reference from profileScores.
    last_scored_at = profile_scores.get(
        "lastScoredAt"
    )

    if last_scored_at is not None:
        state["lastTimestamp"] = parse_timestamp(
            last_scored_at
        ).timestamp()

    return state


def save_user_scores(
    user_id: str,
    result: dict
) -> None:

    state = result["state"]

    scores_to_save = {
        category: {
            "weight": data["weight"],
            "positiveEvents": data["positiveEvents"],
            "negativeEvents": data["negativeEvents"]
        }
        for category, data in state["categories"].items()
    }

    update_fields = {
        f"profileScores.{MODEL_VERSION}.scores":
            scores_to_save,

        f"profileScores.{MODEL_VERSION}.modelVersion":
            MODEL_VERSION
    }

    last_timestamp = state.get("lastTimestamp")

    if last_timestamp is not None:
        update_fields[
            f"profileScores.{MODEL_VERSION}.lastScoredAt"
        ] = datetime.fromtimestamp(
            last_timestamp,
            tz=timezone.utc
        )

    if ObjectId.is_valid(user_id):
        query = {
            "_id": ObjectId(user_id)
        }
    else:
        query = {
            "_id": user_id
        }

    update_result = users_collection.update_one(
        query,
        {
            "$set": update_fields
        }
    )

    if update_result.matched_count == 0:
        raise ValueError(
            f"User not found: {user_id}"
        )


def prepare_event(
    event: dict,
    video_cache: dict
) -> dict:

    prepared = dict(event)

    # Accept enriched video metadata or a video ID.
    video_value = prepared.get("video")

    if video_value is None:
        video_value = (
            prepared.get("videoId")
            or prepared.get("video_id")
        )

    if video_value is None:
        raise ValueError(
            "Event must contain video metadata or videoId."
        )

    # Extract the ID for caching where possible.
    if isinstance(video_value, dict):

        video_id = (
            video_value.get("videoId")
            or video_value.get("_id")
            or video_value.get("id")
            or video_value.get("$oid")
        )

        if isinstance(video_id, dict):
            video_id = video_id.get("$oid")

    elif isinstance(video_value, ObjectId):
        video_id = str(video_value)

    elif isinstance(video_value, str):
        video_id = video_value

    else:
        video_id = None

    cache_key = (
        str(video_id)
        if video_id is not None
        else json.dumps(
            video_value,
            sort_keys=True,
            default=str
        )
    )

    if cache_key not in video_cache:
        video_cache[cache_key] = resolve_video_metadata(
            video_value
        )

    prepared["video"] = video_cache[cache_key]

    if "timestamp" not in prepared:
        raise ValueError(
            "Event timestamp is required."
        )

    prepared["timestamp"] = parse_timestamp(
        prepared["timestamp"]
    )

    return prepared


def process_scoring_events(
    events: list[dict]
) -> dict:

    if not isinstance(events, list):
        raise ValueError(
            "Events must be provided as a list."
        )

    if not events:
        return {
            "modelVersion": MODEL_VERSION,
            "message": "No events to process.",
            "summary": {
                "received": 0,
                "processed": 0,
                "skipped": 0,
                "usersProcessed": 0
            },
            "users": []
        }

    categories = get_active_categories()

    if not categories:
        raise RuntimeError(
            "No active categories found in Reva_Categories."
        )

    grouped_events = defaultdict(list)

    for event in events:

        if not isinstance(event, dict):
            raise ValueError(
                "Every event must be a JSON object."
            )

        user_id = normalize_user_id(
            event.get("userId")
        )

        if not event.get("eventType"):
            raise ValueError(
                "Event type is required."
            )

        if not event.get("timestamp"):
            raise ValueError(
                "Event timestamp is required."
            )

        grouped_events[user_id].append(event)

    results = []

    total_processed = 0
    total_skipped = 0

    video_cache = {}

    with _state_lock:

        for user_id, user_events in grouped_events.items():

            # 1. Find the user.
            user = find_user_document(user_id)

            if user is None:
                raise ValueError(
                    f"User not found: {user_id}"
                )

            # 2. Prepare incoming events.
            prepared_events = [
                prepare_event(
                    event,
                    video_cache
                )
                for event in user_events
            ]

            # 3. Load the user's existing scoring state.
            state = build_scoring_state(
                user,
                categories
            )

            # 4. Calculate updated category scores.
            scoring_result = score_events(
                events=prepared_events,
                categories=categories,
                state=state
            )

            # 5. Save updated scores in MongoDB.
            save_user_scores(
                user_id,
                scoring_result
            )

            summary = scoring_result["summary"]

            total_processed += summary["processed"]
            total_skipped += summary["skipped"]

            results.append({
                "userId": user_id,
                "modelVersion": MODEL_VERSION,
                "scores": scoring_result["scores"],
                "summary": summary
            })

    return {
        "modelVersion": MODEL_VERSION,
        "summary": {
            "received": len(events),
            "processed": total_processed,
            "skipped": total_skipped,
            "usersProcessed": len(results)
        },
        "users": results
    }


def get_user_scoring(user_id: str):

    user_id = normalize_user_id(user_id)

    user = find_user_document(user_id)

    if user is None:
        return None

    categories = get_active_categories()

    state = build_scoring_state(
        user,
        categories
    )

    # Apply decay for the current returned view.
    result = score_events(
        events=[],
        categories=categories,
        state=state,
        as_of_timestamp=datetime.now(timezone.utc)
    )

    return {
        "userId": user_id,
        "modelVersion": MODEL_VERSION,
        "scores": result["scores"]
    }


def get_all_user_scoring():

    categories = get_active_categories()

    users = users_collection.find(
        {},
        {
            "_id": 1,
            f"profileScores.{MODEL_VERSION}": 1
        }
    )

    results = []

    current_time = datetime.now(timezone.utc)

    for user in users:

        user_id = str(user["_id"])

        state = build_scoring_state(
            user,
            categories
        )

        result = score_events(
            events=[],
            categories=categories,
            state=state,
            as_of_timestamp=current_time
        )

        results.append({
            "userId": user_id,
            "modelVersion": MODEL_VERSION,
            "scores": result["scores"]
        })

    return results
