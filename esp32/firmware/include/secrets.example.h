// Copier ce fichier en include/secrets.h puis remplir. secrets.h n'est pas versionné.
#pragma once

#define WIFI_SSID    "NomDuWifi"
#define WIFI_PASS    "MotDePasseWifi"
// IP du PC qui fait tourner le site, sur le même Wi-Fi (ipconfig / ip a)
#define SERVER_URL   "http://192.168.1.20:8000/api/telemetry"
// Laisser vide, ou mettre la même valeur que BP_DEVICE_TOKEN côté serveur
#define DEVICE_TOKEN ""
