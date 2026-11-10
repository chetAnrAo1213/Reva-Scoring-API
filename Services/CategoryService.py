from Config.MongoConfig import categories_collection
def get_active_categories() -> list[str]:

    documents = categories_collection.find(
        {"folderName": {"$exists": True, "$ne": ""}},
        {"_id": 0, "folderName": 1}
    )

    categories = []

    for document in documents:
        folder_name = document.get("folderName")

        if folder_name:
            folder_name = folder_name.strip()

            if folder_name and folder_name not in categories:
                categories.append(folder_name)

    return sorted(categories, key=str.lower)