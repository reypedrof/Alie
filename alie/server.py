import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def latest_report(directory):
    reports = []
    for path in directory.glob("run-*/report.html"):
        run = re.fullmatch(r"run-(\d+)", path.parent.name)
        if run and path.is_file():
            reports.append((int(run[1]), path))
    return max(reports, default=(0, None))[1]


EMPTY_PAGE = b'''<!doctype html>
<html lang="pt-BR"><meta charset="utf-8"><title>Alie</title>
<h1>Cupons de loja</h1><p>Aguardando o primeiro relat&oacute;rio.</p></html>'''


class ReportHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.serve_report(include_body=True)

    def do_HEAD(self):
        self.serve_report(include_body=False)

    def serve_report(self, include_body):
        if urlsplit(self.path).path != "/":
            self.send_error(404)
            return
        report = latest_report(self.server.data_directory)
        revision = '"empty"'
        document = EMPTY_PAGE
        if report:
            try:
                with report.open("rb") as stream:
                    modified = os.fstat(stream.fileno()).st_mtime_ns
                    revision = f'"{report.parent.name}-{modified}"'
                    if include_body:
                        document = stream.read()
            except FileNotFoundError:
                revision = '"empty"'

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("ETag", revision)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            update = f'''<script>
window.setInterval(async () => {{
  try {{
    const response = await fetch('/', {{method: 'HEAD', cache: 'no-store'}});
    if (response.ok && response.headers.get('ETag') !== {json.dumps(revision)}) {{
      window.location.reload();
    }}
  }} catch {{ /* O servidor pode estar reiniciando. A próxima consulta tenta de novo. */ }}
}}, 10000);
</script>'''.encode("utf-8")
            self.wfile.write(document.replace(b"</html>", update + b"</html>", 1))


def main():
    with ThreadingHTTPServer(("0.0.0.0", 8780), ReportHandler) as server:
        server.data_directory = Path(os.environ.get("ALIE_DATA_DIR", "data"))
        print("Relatório disponível na porta 8780.", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
