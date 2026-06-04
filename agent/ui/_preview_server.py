"""Static preview server for the Layla UI shell (dev-only, no backend).

Serves agent/ui/ so the layout/colors/typography can be reviewed without the
full Python stack. API calls (/agent, /health, ...) return 204 so the shell
renders without console errors. NOT for production.
"""
import http.server
import os

UI_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("LAYLA_PREVIEW_PORT", "8777"))

# Routes that the real FastAPI backend would serve; stub them so the shell
# doesn't spew fetch errors while we inspect static styling.
API_PREFIXES = (
    "/agent", "/health", "/wakeup", "/approve", "/v1", "/debate", "/codex",
    "/settings", "/intelligence", "/pairing", "/session", "/learnings",
    "/system_export", "/debug", "/memory", "/research", "/plans", "/plan",
    "/improvements", "/autonomous", "/search", "/obsidian", "/remote", "/setup",
)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI_DIR, **kwargs)

    def translate_path(self, path):
        # Map the production asset prefix onto the ui/ directory root.
        if path.startswith("/layla-ui/"):
            path = path[len("/layla-ui"):]
        if path in ("/", "/ui", "/ui/"):
            path = "/index.html"
        return super().translate_path(path)

    def end_headers(self):
        # Dev preview: never cache, so edits show up on a plain reload.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def _maybe_stub_api(self):
        p = self.path.split("?")[0]
        if p.startswith(API_PREFIXES):
            self.send_response(204)
            self.end_headers()
            return True
        return False

    def do_GET(self):
        if self._maybe_stub_api():
            return
        super().do_GET()

    def do_POST(self):
        if self._maybe_stub_api():
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    # Threading server: the browser holds parallel + keep-alive connections
    # (and an EventSource), which would deadlock a single-threaded server.
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Layla UI preview at http://127.0.0.1:{PORT}/ui/")
        httpd.serve_forever()
