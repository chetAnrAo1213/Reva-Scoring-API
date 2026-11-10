
from bson import ObjectId

from Config.MongoConfig import videos_collection


def extract_video_id(video) -> str | None:

    if isinstance(video, str):

        return video

    if isinstance(video, ObjectId):

        return str(video)

    if isinstance(video, dict):

        video_id = (
            video.get("videoId")
            or video.get("_id")
            or video.get("id")
            or video.get("$oid")
        )

        if isinstance(video_id, dict):

            video_id = video_id.get("$oid")

        if video_id is not None:

            return str(video_id)

    return None


def find_video_document(video_id: str):

    if not video_id:
        return None

    conditions = [
        {"_id": video_id}
    ]

    if ObjectId.is_valid(video_id):

        conditions.insert(
            0,
            {"_id": ObjectId(video_id)}
        )

    return videos_collection.find_one({
        "$or": conditions
    })


def resolve_video_metadata(video) -> dict:

    # First preference: metadata supplied by REVA-Event.
    if isinstance(video, dict):

        folder = video.get("folder")
        duration = video.get("duration")
        title = video.get("title")

        if (
            folder
            and duration is not None
            and title is not None
        ):

            duration = float(duration)

            if duration <= 0:

                raise ValueError(
                    "Video duration must be greater than zero."
                )

            return {
                "videoId": extract_video_id(video),
                "folder": str(folder).strip(),
                "duration": duration,
                "title": str(title)
            }

    # Fallback: resolve metadata using the video ID.
    video_id = extract_video_id(video)

    if not video_id:

        raise ValueError(
            "Video metadata or a valid video ID is required."
        )

    document = find_video_document(video_id)

    if document is None:

        raise ValueError(
            f"Video metadata not found for video ID: {video_id}"
        )

    folder = document.get("folder")
    duration = document.get("duration")
    title = document.get("title")

    if not folder or duration is None:

        raise ValueError(
            f"Incomplete video metadata for video ID: {video_id}"
        )

    duration = float(duration)

    if duration <= 0:

        raise ValueError(
            f"Invalid video duration for video ID: {video_id}"
        )

    return {
        "videoId": str(document["_id"]),
        "folder": str(folder).strip(),
        "duration": duration,
        "title": str(title or "")
    }
