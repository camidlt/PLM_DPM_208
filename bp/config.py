import os

# Base de données : "neo4j" si NEO4J_URI est défini, sinon "memory" (démo sans installation)
BACKEND = os.environ.get("BP_BACKEND") or ("neo4j" if os.environ.get("NEO4J_URI") else "memory")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# URL publique de l'appli encodée dans les QR codes
BASE_URL = os.environ.get("BP_BASE_URL", "http://localhost:5000").rstrip("/")

SECRET_KEY = os.environ.get("BP_SECRET_KEY", "dev-hackathon-battery-passport")

# Comptes de test (PoC : mots de passe en clair, à ne pas faire en production)
ACCOUNTS = {
    "garagiste": dict(password="garage123", role="garagiste", actor_uid="GARAGE-HV",
                      display="Garage Hill Valley"),
    "proprietaire": dict(password="owner123", role="proprietaire", actor_uid="OWNER-FLUX",
                         operator_uid="EO-FLUX", display="Flux Motors - Resp. Battery Passport"),
    "centretri": dict(password="tri123", role="centre_tri", actor_uid="CT-NANTERRE",
                      display="Centre de tri Recyclo Nanterre"),
    "centretri2": dict(password="tri123", role="centre_tri", actor_uid="CT-LYON",
                       display="Centre de tri Rhône Batteries"),
    # Défi 2 : transporteur agréé ADR
    "transporteur": dict(password="trans123", role="transporteur", actor_uid="TR-TRANSBAT",
                         display="TransBat Logistique"),
    # Compte administration globale (supervision & switch)
    "admin": dict(password="admin", role="admin", actor_uid="OWNER-FLUX",
                  operator_uid="EO-FLUX", display="Administrateur Système"),
}

# Défi 2 : notifications par mail. Sans BP_SMTP_HOST, les mails sont simulés
# (enregistrés dans la messagerie de l'appli, rien n'est envoyé).
SMTP_HOST = os.environ.get("BP_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("BP_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("BP_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("BP_SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("BP_SMTP_FROM", "battery-passport@fluxmotors.example")
# Code déchet porté sur les documents : à confirmer avec le centre de tri
WASTE_CODE = os.environ.get("BP_WASTE_CODE", "16 06 05")

# Défi 1 : clé partagée que la passerelle BMS envoie dans l'en-tête X-BMS-Key
# (authentification machine à machine, distincte des comptes utilisateurs)
BMS_API_KEY = os.environ.get("BP_BMS_KEY", "bms-demo-key")
