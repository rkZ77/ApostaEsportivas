import os
import sys

# Evita RuntimeError de JWT_SECRET ausente ao importar auth_utils em dev/CI.
os.environ.setdefault("APP_ENV", "development")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
