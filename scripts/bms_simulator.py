"""Simulateur de trames BMS (Défi 1).

Envoie des trames télémétrie HTTP au backend Battery Passport pour simuler
une séquence de test de diagnostic BMS en direct avec décompte automatique.

Exemples :
    py scripts/bms_simulator.py --battery BAT-002 --module 2
    py scripts/bms_simulator.py --battery BAT-DOC-001 --module 3
    py scripts/bms_simulator.py --battery BAT-002 --module 2 --duration 15
    py scripts/bms_simulator.py --infinite
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime

# Assure le bon encodage sur console Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import requests
except ImportError:
    requests = None
    import urllib.error
    import urllib.request


V_OCV = 3.70     # tension à vide nominale d'un module (V)
I_LOAD = 12.0    # courant de charge (A)
BASE_R = [1.2, 1.3, 1.1, 1.2, 1.4]  # résistance interne normale de base (mOhm)


def build_payload(battery_id, faulty_module, extra_r, source="Passerelle BMS (Diagnostic)",
                  test_status="RUNNING", test_remaining_sec=None, test_duration_sec=15,
                  test_step=1, test_total_steps=7):
    modules = []
    for k, base in enumerate(BASE_R, start=1):
        r = base + random.uniform(-0.04, 0.04) + (extra_r if k == faulty_module else 0.0)
        i = I_LOAD + random.uniform(-0.15, 0.15)
        v_load = V_OCV - (i * r / 1000.0)
        r_calc = (V_OCV - v_load) / i * 1000.0
        temp = 25.0 + (r_calc - 1.2) * 2.2 + random.uniform(-0.3, 0.3)
        modules.append({
            "index": k,
            "internalResistance_mOhm": round(r_calc, 2),
            "temperature_C": round(temp, 1)
        })
    return {
        "batteryId": battery_id,
        "source": source,
        "measuredAt": datetime.now().isoformat(timespec="seconds"),
        "test_status": test_status,
        "test_remaining_sec": test_remaining_sec,
        "test_duration_sec": test_duration_sec,
        "test_step": test_step,
        "test_total_steps": test_total_steps,
        "modules": modules
    }


def send_frame(url, payload, api_key):
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-BMS-Key": api_key,
        "X-Device-Id": "simulator-cli"
    }
    if requests:
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
        return resp.status_code, resp.json()
    else:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Simulateur BMS - Defi 1 Battery Passport")
    parser.add_argument("--battery", default="BAT-DOC-001", help="Identifiant batterie (ex: BAT-DOC-001, BAT-002)")
    parser.add_argument("--module", "--faulty", dest="module", type=int, default=None, help="Numero du module defaillant (1 a 5)")
    parser.add_argument("--duration", type=int, default=15, help="Duree du test en secondes (defaut : 15s)")
    parser.add_argument("--period", type=float, default=2.0, help="Intervalle entre 2 trames en secondes (defaut : 2.0s)")
    parser.add_argument("--normal", type=int, default=2, help="Nombre de mesures saines avant derive")
    parser.add_argument("--step", type=float, default=0.9, help="Hausse de resistance par mesure (mOhm)")
    parser.add_argument("--max-extra", type=float, default=5.5, help="Hausse maximale ajoutee au module")
    parser.add_argument("--infinite", action="store_true", help="Tourner en continu sans arret automatique")
    parser.add_argument("--reset", "--clean", action="store_true", help="Reinitialiser la batterie a un etat sain (modules conformes < 2.0 mOhm)")
    parser.add_argument("--url", default="http://localhost:5000/api/telemetry", help="URL API telemetrie")
    parser.add_argument("--key", default="bms-demo-key", help="Cle API BMS")

    args = parser.parse_args()

    if args.module is None:
        args.module = 3 if "DOC" in args.battery.upper() else 2

    if args.reset:
        print("=" * 70)
        print(f"  RÉINITIALISATION DE LA BATTERIE {args.battery}")
        print("=" * 70)
        payload = build_payload(args.battery, args.module, 0.0,
                                source="Passerelle BMS (Initialisation)",
                                test_status="RESET", test_remaining_sec=0,
                                test_duration_sec=0, test_step=1, test_total_steps=1)
        for m in payload["modules"]:
            m["internalResistance_mOhm"] = round(1.2 + random.uniform(-0.05, 0.05), 2)
        try:
            status, resp = send_frame(args.url, payload, args.key)
            print(f"  ✅ Batterie {args.battery} réinitialisée avec succès !")
            print("  Tous les modules sont sains (< 2.0 mΩ), statut de test remis à 'Prêt'.\n")
        except Exception as e:
            print(f"  ❌ Erreur lors de la réinitialisation : {e}")
        return

    total_steps = 0 if args.infinite else max(1, int(args.duration / args.period))

    print("=" * 70)
    print("  BMS DIAGNOSTIC RUNNER - DEFI 1 (TÉLÉMÉTRIE)")
    print(f"  Batterie cible    : {args.battery}")
    print(f"  Module testé      : Module {args.module}")
    if args.infinite:
        print("  Mode              : Continu (Appuyez sur Ctrl+C pour arreter)")
    else:
        print(f"  Duree du test     : {args.duration} secondes ({total_steps} trames)")
    print(f"  Envoi vers        : {args.url}")
    print("=" * 70 + "\n")

    alert_triggered = False
    tick = 0
    extra = 0.0
    try:
        while True:
            if total_steps and tick >= total_steps:
                break

            remaining_sec = max(0, int((total_steps - tick) * args.period)) if total_steps else 0
            time_str = f"{remaining_sec:02d}s restantes" if total_steps else "continu"

            extra = 0.0 if tick < args.normal else min(args.max_extra, (tick - args.normal + 1) * args.step)
            payload = build_payload(
                args.battery, args.module, extra,
                test_status="RUNNING",
                test_remaining_sec=remaining_sec,
                test_duration_sec=args.duration,
                test_step=tick + 1,
                test_total_steps=total_steps
            )

            try:
                status, resp = send_frame(args.url, payload, args.key)
                alerts = resp.get("alerts") or []
                if alerts:
                    alert_triggered = True
                    alert_str = " ⚠️ [ALERTE SEUIL DÉPASSÉ]"
                else:
                    alert_str = " ✓ (normal)"

                step_str = f"[{tick+1:02d}/{total_steps:02d} | {time_str}]" if total_steps else f"[{tick+1:03d}]"
                modules_str = " | ".join(f"M{m['index']}={m['internalResistance_mOhm']:4.1f}mΩ" for m in payload["modules"])
                print(f"{step_str} {modules_str}{alert_str}")
            except Exception as e:
                print(f"[{tick+1:02d}] Erreur envoi : {e}")

            tick += 1
            if total_steps and tick >= total_steps:
                break
            time.sleep(args.period)

        # Trame de complétion
        payload_done = build_payload(
            args.battery, args.module, extra,
            test_status="COMPLETED",
            test_remaining_sec=0,
            test_duration_sec=args.duration,
            test_step=total_steps,
            test_total_steps=total_steps
        )
        try:
            send_frame(args.url, payload_done, args.key)
        except Exception:
            pass

        print("\n" + "=" * 70)
        print(f"  ✅ SÉQUENCE DE DIAGNOSTIC BMS TERMINÉE ({args.duration}s)")
        if alert_triggered:
            print(f"  Statut : Anomalie detectee sur le Module {args.module} (seuil constructeur depasse).")
            print("  Action : Alerte enregistree dans le Battery Passport. Formulaire pre-rempli.")
        else:
            print("  Statut : Tous les modules sont conformes aux specifications constructeur.")
        print("=" * 70)
        print("La session de test est maintenant fermee.\n")

    except KeyboardInterrupt:
        print("\nSimulation interrompue manuellement.")


if __name__ == "__main__":
    main()
