"""Pytest bootstrap: put the backend dir on sys.path and use an isolated DB."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

# Isolated, disposable database for the acceptance test.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_acceptance.db")
os.environ.setdefault("AUTO_SEED", "true")
os.environ.setdefault("PUBLIC_BASE_URL", "http://testserver")
os.environ.setdefault("SECRET_KEY", "test-secret")
# Tests must never inherit a developer's real SMTP credentials or configured
# external CTA destination from the project-root .env.
os.environ["EMAIL_PROVIDER"] = "mock"
os.environ["INVITATION_DESTINATION_URL"] = ""
