"""Écrit data/seed.cypher (à coller dans Neo4j Browser ou à lancer avec cypher-shell)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bp import seed_data  # noqa: E402

path = os.path.join(ROOT, "data", "seed.cypher")
with open(path, "w", encoding="utf-8") as f:
    f.write("// Jeu de données de démo Battery Passport (généré par scripts/export_cypher.py)\n")
    for stmt in seed_data.cypher_statements():
        f.write(stmt + ";\n")
print(f"{path} écrit ({len(seed_data.cypher_statements())} instructions)")
