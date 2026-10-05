import os
import tempfile

# Muss vor dem ersten Import von 'app' passieren: eigene Daten fuer die Tests.
os.environ["HEIZKOSTEN_DATA"] = tempfile.mkdtemp(prefix="hk-test-")
os.environ.pop("HEIZKOSTEN_PASSWORT", None)
