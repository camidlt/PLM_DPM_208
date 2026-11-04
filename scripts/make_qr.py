"""Génère les QR codes (PNG) à imprimer/coller sur les batteries de démo.

Usage :  BP_BASE_URL=http://192.168.1.20:8000 python scripts/make_qr.py
Le QR encode BP_BASE_URL/b/<ID> : scanné avec l'appareil photo d'une tablette ou d'un
téléphone sur le même Wi-Fi, il ouvre directement le passeport (après connexion).
Nécessite `qrcode[pil]` (pip install "qrcode[pil]") ou, à défaut, opencv-python.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bp import config, seed_data  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qr")


def save_qr(text, path):
    try:
        import qrcode
        qrcode.make(text, box_size=10, border=4).save(path)
    except ImportError:
        import cv2
        img = cv2.QRCodeEncoder.create().encode(text)
        img = cv2.resize(img, (img.shape[1] * 12, img.shape[0] * 12), interpolation=cv2.INTER_NEAREST)
        img = cv2.copyMakeBorder(img, 48, 48, 48, 48, cv2.BORDER_CONSTANT, value=255)
        cv2.imwrite(path, img)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for b in seed_data.BATTERIES:
        url = f"{config.BASE_URL}/b/{b['id']}"
        save_qr(url, os.path.join(OUT, f"{b['id']}.png"))
        print(f"{b['id']}.png -> {url}")
