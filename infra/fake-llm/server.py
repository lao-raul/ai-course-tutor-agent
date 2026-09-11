"""Tiny deterministic OpenAI-compatible server used only by CI smoke tests."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSION = 1024


def _vector(value: str) -> list[float]:
    """Return a stable vector that makes the generated CI fixture retrievable."""
    return [1.0, *([0.0] * (DIMENSION - 1))] if value else [0.0] * DIMENSION


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/v1/models":
            self._json(200, {"data": [{"id": "ci-chat"}, {"id": "ci-embedding"}]})
        else:
            self._json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/embeddings":
            inputs = body.get("input", [])
            self._json(
                200,
                {
                    "data": [
                        {"index": index, "embedding": _vector(text)}
                        for index, text in enumerate(inputs)
                    ]
                },
            )
            return
        if self.path == "/v1/chat/completions":
            messages = body.get("messages", [])
            prompt = "\n".join(str(message.get("content", "")) for message in messages)
            chunk_match = re.search(r"\[chunk_id=([0-9a-f-]{36})\]", prompt, re.IGNORECASE)
            if chunk_match is None:
                self._json(422, {"detail": "CI prompt did not contain grounded evidence"})
                return
            answer = (
                "The generated fixture says grounded tutoring answers must cite "
                f"the supplied course material [Source 1].\nCITATIONS:"
                f'[{{"source":1,"chunk_id":"{chunk_match.group(1)}"}}]'
            )
            events = [
                f"data: {json.dumps({'choices': [{'delta': {'content': answer}}]})}\n\n",
                "data: [DONE]\n\n",
            ]
            payload = "".join(events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self._json(404, {"detail": "not found"})

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8082), Handler).serve_forever()  # noqa: S104
