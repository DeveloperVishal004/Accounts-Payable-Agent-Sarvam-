import os
import tempfile

# Must run before any app import: isolated DB, offline fixtures, never spend Sarvam credits in tests.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["SARVAM_MODE"] = "mock"
