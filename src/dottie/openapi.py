"""Print the API's OpenAPI schema, for the frontend's generated types (npm run gen:api)."""

import json

from .api.app import create_app
from .config import settings_without_env_file

if __name__ == "__main__":
    print(json.dumps(create_app(settings_without_env_file()).openapi(), indent=1))
