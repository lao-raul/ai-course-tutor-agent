"""Tiny deterministic OpenAI-compatible server used only by CI smoke tests."""

from __future__ import annotations

import hashlib
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSION = 1024


def _vector(value: str) -> list[float]:
    digest = hashlib.sha256(value.encode()).digest()
    values = [(digest[index % len(digest)] - 127.5) / 127.5 for index in range(DIMENSION)]
    norm = math.sqrt(sum(item * item for item in values)) or 1.0
    return [item / norm for item in values]


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
            payload = (
                b'data: {"choices":[{"delta":{"content":"CI fake answer."}}]}\n\ndata: [DONE]\n\n'
            )
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
