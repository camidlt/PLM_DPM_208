"""
Émulateur BMS (plan B si Wokwi ne marche pas) – simule les 5 modules de la batterie.

Scénario : N mesures normales, puis le module défectueux dérive jusqu'au critique.

  python bms_emulator.py                      # envoi HTTP vers le backend local
  python bms_emulator.py --mode mqtt          # envoi MQTT (même topic que l'ESP32)
  python bms_emulator.py --normal 5 --step 4  # dérive plus rapide
"""
import argparse
import json
import random
import time

import requests

V_OCV = 3.70     # tension à vide d'un module (V)
I_LOAD = 12.0    # courant de charge (A)
BASE_R = [7.8, 8.1, 8.0, 7.9, 8.3]  # résistance interne normale (mΩ)


def build_payload(battery_id, faulty, extra_r):
    modules = []
    for k, base in enumerate(BASE_R, start=1):
        r = base + random.uniform(-0.3, 0.3) + (extra_r if k == faulty else 0)
        i = I_LOAD + random.uniform(-0.2, 0.2)
        v_load = V_OCV - i * r / 1000           # chute de tension sous charge
        r_calc = (V_OCV - v_load) / i * 1000    # R = ΔV / I
        t = 25 + (r_calc - 8) * 0.35 + random.uniform(-0.5, 0.5)
        modules.append({"id": k, "v_ocv": V_OCV, "v": round(v_load, 4), "i": round(i, 2),
                        "r_mohm": round(r_calc, 1), "t": round(t, 1)})
    return {"batteryId": battery_id, "modules": modules}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--battery", default="DLR-1985")
    ap.add_argument("--faulty", type=int, default=3, help="module défectueux (1-5)")
    ap.add_argument("--normal", type=int, default=10, help="nb de mesures normales avant dérive")
    ap.add_argument("--step", type=float, default=3.0, help="hausse de R par mesure (mΩ)")
    ap.add_argument("--max-extra", type=float, default=45.0)
    ap.add_argument("--period", type=float, default=2.0, help="secondes entre 2 mesures")
    ap.add_argument("--mode", choices=["http", "mqtt"], default="http")
    ap.add_argument("--url", default="http://localhost:8000/api/telemetry")
    ap.add_argument("--mqtt-host", default="broker.hivemq.com")
    ap.add_argument("--topic-prefix", default="esilv-hack-2026/equipe-XX")
    a = ap.parse_args()

    client = None
    if a.mode == "mqtt":
        import paho.mqtt.client as mqtt
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.connect(a.mqtt_host, 1883)
        client.loop_start()
    topic = f"{a.topic_prefix}/battery/{a.battery}/telemetry"

    tick = 0
    while True:
        extra = 0.0 if tick < a.normal else min(a.max_extra, (tick - a.normal + 1) * a.step)
        p = build_payload(a.battery, a.faulty, extra)
        if client:
            client.publish(topic, json.dumps(p))
        else:
            requests.post(a.url, json=p, timeout=5).raise_for_status()
        rs = " | ".join(f"M{m['id']}={m['r_mohm']:5.1f}" for m in p["modules"])
        print(f"[{tick:03d}] {rs} mΩ")
        tick += 1
        time.sleep(a.period)


if __name__ == "__main__":
    main()
