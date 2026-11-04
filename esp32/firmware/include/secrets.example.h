// Copier ce fichier en include/secrets.h puis remplir. secrets.h n'est pas versionné.
#pragma once

// Mode 2 et 3 : Wi-Fi 2,4 GHz, le même réseau que le PC
#define WIFI_SSID    "NomDuWifi"
#define WIFI_PASS    "MotDePasseWifi"

// Mode 2 (HTTP) : IP du PC qui fait tourner le site (ipconfig / ip a)
#define SERVER_URL   "http://192.168.1.20:8000/api/telemetry"
// Laisser vide, ou mettre la même valeur que BP_DEVICE_TOKEN côté serveur
#define DEVICE_TOKEN ""

// Mode 3 (MQTT) : mêmes valeurs que MQTT_HOST et TOPIC_PREFIX côté serveur
#define MQTT_HOST    "broker.hivemq.com"
#define MQTT_PORT    1883
#define TOPIC_PREFIX "esilv-hack-2026/equipe-XX"
