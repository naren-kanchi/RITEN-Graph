"""Create .env from .env.example, replacing every change-me with a random secret.

Refuses to touch an existing .env so that credentials are never rotated by accident.
"""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; leaving it untouched.")
lines = []
for line in (root / ".env.example").read_text().splitlines():
    if line.endswith("=change-me"):
        line = line.replace("change-me", secrets.token_urlsafe(24))
    lines.append(line)
target.write_text("\n".join(lines) + "\n")
print("Wrote .env with random secrets. Seed logins are in SEED_* inside it.")
