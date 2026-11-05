"""Défi 2 : notifications in-app et mail.

Chaque notification est enregistrée dans le graphe ((:Message)-[:SENT_TO]->(:Actor)) et
s'affiche dans la messagerie de l'appli. Si BP_SMTP_HOST est configuré, un mail est
aussi envoyé à l'adresse de l'acteur ; sinon le mail est simulé (channel = "mail simulé").
Un échec d'envoi n'interrompt jamais le workflow.
"""
import logging
import smtplib
from email.message import EmailMessage

from . import config

log = logging.getLogger(__name__)


def _send_mail(to, subject, body):
    if not (config.SMTP_HOST and to):
        return "mail simulé"
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, f"[Battery Passport] {subject}"
        msg.set_content(body)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as s:
            s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
        return "mail envoyé"
    except Exception as e:  # noqa: BLE001 - la notification ne doit pas bloquer le transfert
        log.warning("Envoi du mail à %s impossible : %s", to, e)
        return "mail en échec"


def notify(repo, actor_uids, subject, body, link="", battery_id="", order_uid=""):
    """Envoie la même notification à plusieurs acteurs (doublons et None ignorés)."""
    for uid in dict.fromkeys(u for u in actor_uids if u):
        actor = repo.get_actor(uid)
        if actor is None:
            continue
        mail = _send_mail(actor.get("email"), subject, f"{body}\n\n{config.BASE_URL}{link}")
        repo.add_message(uid, dict(subject=subject, body=body, link=link, batteryId=battery_id,
                                   orderUid=order_uid, channel=f"in-app + {mail}",
                                   email=actor.get("email") or ""))
