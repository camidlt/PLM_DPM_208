"""Charge (ou recharge) le jeu de démo dans Neo4j.

Usage :  NEO4J_URI=bolt://localhost:7687 NEO4J_PASSWORD=xxx python scripts/seed_neo4j.py
Ne touche qu'aux nœuds de démo (uid connus) + Notification/TransferOrder/Event :
les données du dump officiel éventuellement importé sont conservées.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bp.neo4j_repo import Neo4jRepo  # noqa: E402

repo = Neo4jRepo()
repo.reset()
print("Données de démo chargées :")
for b in repo.list_batteries():
    print(f"  {b['batteryId']:12} {b['status']:9} SOH {b['soh']} %  {b['location']}")
