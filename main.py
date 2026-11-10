
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from Services.ScoringService import (
    process_scoring_events,
    get_user_scoring,
    get_all_user_scoring
)

from Services.CategoryService import get_active_categories

from Models.DynamicScoringModel import MODEL_VERSION


app = FastAPI(
    title="REVA Scoring API",
    description="Dynamic user category scoring service",
    version="2.0.0"
)


class EventsRequest(BaseModel):

    events: list[dict[str, Any]] = Field(
        ...,
        min_length=1
    )


@app.get("/")
def root():

    return {
        "service": "REVA Scoring API",
        "status": "running",
        "modelVersion": MODEL_VERSION
    }


@app.get("/health")
def health():

    return {
        "status": "healthy",
        "service": "REVA Scoring API"
    }


@app.get("/api/scoring/categories")
def get_categories():

    try:

        categories = get_active_categories()

        return {
            "totalCategories": len(categories),
            "categories": categories
        }

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@app.post("/api/scoring/events")
def submit_scoring_events(request: EventsRequest):

    try:

        return process_scoring_events(
            request.events
        )

    except (ValueError, TypeError, KeyError) as error:

        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@app.get("/api/scoring/users")
def get_all_scoring():

    try:

        return {
            "modelVersion": MODEL_VERSION,
            "users": get_all_user_scoring()
        }

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@app.get("/api/scoring/users/{user_id}")
def get_scoring(user_id: str):

    try:

        result = get_user_scoring(user_id)

        if result is None:

            raise HTTPException(
                status_code=404,
                detail="User scoring profile not found."
            )

        return result

    except HTTPException:
        raise

    except ValueError as error:

        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
):

    body = await request.body()

    print(
        "\n========== SCORING API VALIDATION ERROR =========="
    )

    print("Request URL:", request.url)

    print(
        "Request body:",
        body.decode("utf-8", errors="replace")
    )

    print("Validation errors:", exc.errors())

    print(
        "==================================================\n"
    )

    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({
            "message": "Invalid scoring request.",
            "errors": exc.errors()
        })
    )
