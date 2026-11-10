
import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DATABASE_NAME = os.getenv(
    "MONGO_DATABASE",
    "Reva-Video-Data"
)

if not MONGO_URI:
    raise RuntimeError(
        "MONGO_URI is not configured."
    )

client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000
)

# Verify MongoDB connectivity.
client.admin.command("ping")

database = client[DATABASE_NAME]

# REVA collections.
users_collection = database["User_Account_OAUTH"]
videos_collection = database["CloudinaryMetaData"]
categories_collection = database["Reva_Categories"]
