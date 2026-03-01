"""Self-contained HTTP server for Flint simulation results."""

import json
import os

from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TypeAlias
from urllib.parse import urlparse, parse_qs

SimulationData: TypeAlias = dict[str, object]
SimulateFunc: TypeAlias = Callable[[str, int | None, int | None], SimulationData | None]

_WEB_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web'))

_MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css',
  '.js': 'application/javascript',
}


def _make_handler(data: SimulationData, simulate: SimulateFunc, scenarios: list[str]):
  """Create an HTTP request handler class bound to simulation data and a re-run callable.

  Args:
    data: Current simulation data dict, served at /data and updated when /simulate is called.
    simulate: Callable that re-runs the simulation with optional start year, end year,
      and scenario name. None values use scenario defaults.
    scenarios: Valid scenario names accepted by /simulate.
  """

  class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
      pass  # Suppress default request logging

    def _send_json(self, body: dict, status: int = 200) -> None:
      encoded = json.dumps(body).encode()
      self.send_response(status)
      self.send_header('Content-Type', 'application/json')
      self.send_header('Content-Length', len(encoded))
      self.end_headers()
      self.wfile.write(encoded)

    def do_GET(self):
      nonlocal data
      parsed = urlparse(self.path)
      path = parsed.path

      if path == '/data':
        self._send_json(data)
        return

      if path == '/simulate':
        params = parse_qs(parsed.query)

        # start_year and end_year are optional; absent means use scenario defaults.
        start_year = end_year = None
        if 'start_year' in params or 'end_year' in params:
          try:
            start_year = int(params['start_year'][0])
            end_year = int(params['end_year'][0])
          except (KeyError, ValueError, IndexError):
            self._send_json({'error': 'start_year and end_year must both be integers'}, 400)
            return

        scenario_name = data['scenario']['name']
        if 'scenario' in params:
          scenario_name = params['scenario'][0]
          if scenario_name not in scenarios:
            self._send_json({'error': 'Unknown scenario.'}, 400)
            return

        new_data = simulate(scenario_name, start_year, end_year)
        if new_data is None:
          self._send_json({'error': 'No simulation results. Check your date ranges.'}, 400)
          return

        data = new_data
        self._send_json(data)
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


def serve(data: SimulationData, simulate: SimulateFunc, scenarios: list[str], port: int = 8080):
  """Starts the HTTP server and blocks until Ctrl-C.

  Args:
    data: Initial simulation results dict to expose at /data.
    simulate: Callable that re-runs the simulation with optional start year, end year,
      and scenario name.
    scenarios: Valid scenario names for /simulate.
    port: Port to listen on.
  """
  handler = _make_handler(data, simulate, scenarios)
  server = HTTPServer(('127.0.0.1', port), handler)
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    pass
  finally:
    server.server_close()
