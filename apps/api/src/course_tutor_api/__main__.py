"""Run the API server directly via `python -m course_tutor_api`."""

from __future__ import annotations

import uvicorn

from course_tutor_api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)  # noqa: S104
