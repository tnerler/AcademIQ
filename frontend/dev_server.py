"""Frontend için basit geliştirme sunucusu.

- frontend/ klasörünü http://localhost:3000 adresinden servis eder
  (backend CORS ayarında izinli port 3000).
- Mock modda CV PDF önizlemesi için /mock-pdf/<id>.pdf isteklerini
  data/raw/fake_akademik_cvler/ klasöründen karşılar.
- Sadece 127.0.0.1'e bağlanır, önbelleği kapatır.

Çalıştırma (repo kökünden):
    python frontend/dev_server.py
"""

import http.server
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

FRONTEND = Path(__file__).resolve().parent
CV_PDFS = FRONTEND.parent / "data" / "raw" / "fake_akademik_cvler"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def translate_path(self, path):
        url_path = unquote(urlparse(path).path)
        if url_path.startswith("/mock-pdf/"):
            name = os.path.basename(url_path)
            if name.lower().endswith(".pdf"):
                return str(CV_PDFS / name)
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    Handler.extensions_map[".js"] = "text/javascript"
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"AcademIQ frontend: http://localhost:{PORT}")
        httpd.serve_forever()
