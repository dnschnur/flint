"""Self-contained HTTP server for Flint simulation results."""

import json
import os

from http.server import BaseHTTPRequestHandler, HTTPServer

_WEB_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web'))

_MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css',
  '.js': 'application/javascript',
}


def _make_handler(data: dict):
  """Create an HTTP request handler class bound to simulation data."""

  class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
      pass  # Suppress default request logging

    def do_GET(self):
      path = self.path.split('?')[0]

      if path == '/data':
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
        return

      if path == '/':
        path = '/index.html'

      file_path = os.path.realpath(os.path.join(_WEB_ROOT, path.lstrip('/')))

      if not file_path.startswith(_WEB_ROOT + os.sep):
        self.send_error(403)
        return

      if not os.path.isfile(file_path):
        self.send_error(404)
        return

      ext = os.path.splitext(file_path)[1]
      mime = _MIME_TYPES.get(ext, 'application/octet-stream')

      with open(file_path, 'rb') as f:
        body = f.read()

      self.send_response(200)
      self.send_header('Content-Type', mime)
      self.send_header('Content-Length', len(body))
      self.end_headers()
      self.wfile.write(body)

  return Handler


def serve(data: dict, port: int = 8080):
  """Starts the HTTP server and blocks until Ctrl-C.

  Args:
    data: Simulation results dict to expose at /data.
    port: Port to listen on.
  """
  handler = _make_handler(data)
  server = HTTPServer(('', port), handler)
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    pass
  finally:
    server.server_close()
