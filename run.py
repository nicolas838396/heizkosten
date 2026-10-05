"""Startet die Heizkosten-Webseite (Port 8080) und den Sammler fuer die Funkdaten."""

import os

from app import collector
from app.web import create_app


def main():
    app = create_app()
    collector.start_background(30)
    port = int(os.environ.get("PORT", "8080"))
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=4)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
