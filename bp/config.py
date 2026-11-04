import os

# Base de données : "neo4j" si NEO4J_URI est défini, sinon "memory" (démo sans installation)
BACKEND = os.environ.get("BP_BACKEND") or ("neo4j" if os.environ.get("NEO4J_URI") else "memory")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# URL publique de l'appli, encodée dans les QR codes (mettre l'IP du PC sur le Wi-Fi
# pour scanner depuis une tablette/un téléphone, ex. http://192.168.1.20:8000)
BASE_URL = os.environ.get("BP_BASE_URL", "http://localhost:8000").rstrip("/")

SECRET_KEY = os.environ.get("BP_SECRET_KEY", "dev-hackathon-battery-passport")

# Comptes de test (PoC : mots de passe en clair, à ne pas faire en production)
ACCOUNTS = {
    "garagiste": dict(password="garage123", role="garagiste", actor_uid="GARAGE-HV",
                      display="Garage Hill Valley"),
    "proprietaire": dict(password="owner123", role="proprietaire", actor_uid="OWNER-FLUX",
                         operator_uid="EO-FLUX", display="Flux Motors, responsable Battery Passport"),
    "centretri": dict(password="tri123", role="centre_tri", actor_uid="CT-NANTERRE",
                      display="Centre de tri Recyclo Nanterre"),
    "centretri2": dict(password="tri123", role="centre_tri", actor_uid="CT-LYON",
                       display="Centre de tri Rhône Batteries"),
}
