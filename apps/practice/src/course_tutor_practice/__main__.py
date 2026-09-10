import uvicorn


def main() -> None:
    uvicorn.run(
        "course_tutor_practice.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - container entrypoint must listen on the pod interface
        port=8001,
    )


if __name__ == "__main__":
    main()
