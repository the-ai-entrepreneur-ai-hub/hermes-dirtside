"""Forward container-loopback HTTP over Docker's stdio, without a host listener."""
import base64
import json
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def serve():
    pending, lock = {}, threading.Lock()

    def emit(value):
        with lock:
            print(json.dumps(value), flush=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            key = str(id(self))
            response = queue.Queue()
            with lock:
                pending[key] = response
            try:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                emit(dict(id=key, path=self.path, authorization=self.headers.get("Authorization", ""),
                          body=base64.b64encode(body).decode()))
                data = response.get(timeout=45)
                body = base64.b64decode(data["body"])
                self.send_response(data["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (OSError, queue.Empty):
                self.close_connection = True
            finally:
                with lock:
                    pending.pop(key, None)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    emit(dict(port=server.server_port))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for line in sys.stdin:
            data = json.loads(line)
            with lock:
                target = pending.get(data["id"])
            if target is not None:
                target.put(data)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    serve()
