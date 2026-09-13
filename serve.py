"""Static server for web/ that forbids browser caching, so edits show on plain reload. Run: python3 serve.py [port]"""
import http.server, os, sys
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate"); self.send_header("Expires", "0")
        super().end_headers()
    def log_message(self, *a): pass
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
print(f"GreenRank at http://localhost:{port}  (Ctrl+C to stop)")
http.server.ThreadingHTTPServer(("", port), H).serve_forever()
