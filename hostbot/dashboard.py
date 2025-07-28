from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from typing import Callable, Optional


class DashboardServer:
    """Simple HTTP dashboard for HostBot."""

    def __init__(
        self,
        host: str,
        port: int,
        on_refresh: Callable[[], None],
        get_queue_size: Callable[[], int],
    ):
        self.server = HTTPServer((host, port), self.make_handler(on_refresh, get_queue_size))
        self.thread: Optional[threading.Thread] = None

    @staticmethod
    def make_handler(on_refresh: Callable[[], None], get_queue_size: Callable[[], int]):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    queue_size = get_queue_size()
                    html = f"""
                    <html><body>
                    <h1>HostBot Dashboard</h1>
                    <p>Queue size: {queue_size}</p>
                    <form method='POST' action='/refresh'>
                        <button type='submit'>Refresh Host Command</button>
                    </form>
                    </body></html>
                    """
                    self.wfile.write(html.encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/refresh":
                    on_refresh()
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                return  # suppress logging

        return Handler

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.thread:
            self.server.shutdown()
            self.thread.join()
            self.thread = None
