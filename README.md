# DoorBird Integration für Unfolded Circle Remote Two/3

Integration für [DoorBird](https://www.doorbird.com) Video-Türstationen für die
[Unfolded Circle Remote Two/3](https://www.unfoldedcircle.com), basierend auf der
[ucapi Python-Bibliothek](https://github.com/unfoldedcircle/integration-python-library)
und der [DoorBird LAN-2-LAN API](https://www.doorbird.com/api).

## Funktionen

| Entität | Typ | Beschreibung |
|---|---|---|
| Tür öffnen | Button | Löst das Türöffner-Relais aus (bei mehreren Relais ein Button pro Relais) |
| IR-Licht | Button | Schaltet das Infrarot-Licht der Türstation ein |
| Klingel | Sensor (binär) | `ON`, solange die Klingel gedrückt wird |
| Bewegung | Sensor (binär) | `ON`, solange der Bewegungsmelder auslöst |
| Letztes Ereignis | Sensor | Letztes Klingel-/Bewegungsereignis mit Uhrzeit |

Klingel- und Bewegungsereignisse werden in Echtzeit über den
DoorBird-Monitor-Stream (`/bha-api/monitor.cgi`) empfangen — die Sensoren können
z. B. in Aktivitäten oder auf dem Startbildschirm angezeigt werden.

## Voraussetzungen

- DoorBird-Gerät im selben Netzwerk wie die Remote
- Ein DoorBird-Benutzer mit folgenden Berechtigungen
  (DoorBird App → Administration → Benutzer → Berechtigungen):
  - **API-Operator**
  - **Immer sehen** (Watch always)
  - **Relais** (für die Türöffner-Buttons)

> **Hinweis:** Der Benutzername ist der App-Benutzer im Format `abcdef0001`,
> nicht die E-Mail-Adresse des DoorBird-Kontos.

## Installation auf der Remote (empfohlen)

Ab Firmware 2.2.0 können Custom-Integrationen direkt auf der Remote installiert werden:

1. Neueste `uc-intg-doorbird-<version>-aarch64.tar.gz` von den
   [Releases](https://github.com/mabikus/uc-intg-doorbird/releases) herunterladen.
2. Web-Konfigurator der Remote öffnen → **Integrations** → **Install custom** →
   die heruntergeladene Datei hochladen.
3. Integration auswählen und dem Setup folgen: IP-Adresse, Benutzername und
   Passwort der DoorBird eingeben.
4. Die Entitäten (Tür öffnen, IR-Licht, Klingel, Bewegung, Letztes Ereignis)
   der Remote hinzufügen.

## Alternativ: Betrieb als Docker-Container

Die Integration kann auch auf einem Server/NAS im Netzwerk laufen und wird
dann von der Remote per mDNS gefunden:

```bash
docker compose up -d
```

## Entwicklung

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 intg-doorbird/driver.py
```

Nützliche Umgebungsvariablen:

| Variable | Beschreibung |
|---|---|
| `UC_CONFIG_HOME` | Verzeichnis für die Konfigurationsdatei |
| `UC_INTEGRATION_HTTP_PORT` | WebSocket-Port des Treibers (Standard: 9099) |
| `UC_LOG_LEVEL` | Log-Level (`DEBUG`, `INFO`, …) |

Release bauen: Ein Tag `v*` pushen — die GitHub Action baut das
aarch64-Archiv mit [pyinstaller](https://hub.docker.com/r/unfoldedcircle/r2-pyinstaller)
und hängt es an das Release an.

---

## English summary

DoorBird video door station integration for the Unfolded Circle Remote Two/3.
Provides buttons to open the door relay(s) and switch on the IR light, plus
sensors for real-time doorbell and motion events (via the DoorBird monitor API).

Setup requires the DoorBird IP address and an app user (format `abcdef0001`)
with *API operator*, *watch always* and *relay* permissions. Install the
`aarch64.tar.gz` from the releases page via the web configurator
(**Integrations → Install custom**), or run the driver externally with Docker.

## Lizenz

[Mozilla Public License 2.0](LICENSE)
