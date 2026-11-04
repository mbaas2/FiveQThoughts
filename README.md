# FiveQThoughts

Kompakte, plattformübergreifende App (**macOS & Windows**) zum schnellen Sichten, Kopieren und Aufräumen der **5 neuesten Quick Thoughts** in **TheBrain 15** über die offizielle lokale REST-API (`/api/v2/quick-thoughts`).

## Features

- **5 neueste Quick Thoughts als Karten**: Liest die Quick-Thoughts-Inbox live über die TheBrain 15 Local API (`GET /api/v2/quick-thoughts` & `GET /api/v2/quick-thoughts/{id}`).
- **Notiztext & Grafiken auf einen Blick**:
  - Zeigt den vollständigen Notiztext sowie verknüpfte URLs.
  - Zeigt sowohl **im Text eingebettete Grafiken** (`/api/v2/quick-thoughts/{id}/images/{fileName}` bzw. Data-URIs) als auch **an die Notiz angehängte Grafiken** (`/api/v2/quick-thoughts/{id}/files/{fileId}`) inkl. Lightbox-Vorschau an.
- **Direkte Clipboard-Aktionen pro Karte**:
  - **📋 Text kopieren**: Kopiert den Notiztext (bzw. Titel/Links) direkt in die System-Zwischenablage.
  - **🖼️ Grafik kopieren**: Kopiert eingebettete oder angehängte Grafiken als echtes Bild (PNG/Bitmap) in die Betriebssystem-Zwischenablage (unter macOS via `osascript`/`sips`, unter Windows via PowerShell `System.Windows.Forms.Clipboard`).
- **🗑️ Löschen & Nachladen**:
  - Löscht den Quick Thought über `DELETE /api/v2/quick-thoughts/{id}` und lädt automatisch den nächstälteren Quick Thought nach, sodass immer 5 Karten sichtbar bleiben.
  - Wahlweise mit Sicherheitsabfrage (`Löschen? Ja / Nein`) oder per Schalter **„Sofort löschen“** mit einem Klick.
- **Keine externen Abhängigkeiten**: Läuft mit der reinen Python-3-Standardbibliothek auf macOS und Windows und öffnet sich automatisch als kompaktes App-Fenster.

## Voraussetzungen

- **TheBrain 15** läuft lokal (Standard-Port: `http://localhost:11524`).
- **Local API Key** aus **TheBrain 15 → Settings → User → Local API** *(Hinweis: Nicht der MCP-Key aus den AI-Einstellungen, da `/api/v2/quick-thoughts` den Local-API-Key erwartet)*.
- **Python 3.9+** (auf macOS und Windows ohne `pip install` direkt lauffähig).

## Starten

### macOS
Per Doppelklick auf `run_mac.command` im Finder oder im Terminal:
```bash
python3 app.py
```

### Windows
Per Doppelklick auf `run_windows.bat` oder in PowerShell / CMD:
```powershell
python app.py
```

## Konfiguration

Beim ersten Start (oder über den Button **⚙ API** oben rechts in der App) kann der **Local API Key** sowie die Server-URL (`http://localhost:11524`) eingetragen werden. Die Einstellungen werden lokal in `config.local.json` gespeichert (in `.gitignore` ausgeschlossen).

Alternativ per Umgebungsvariable oder CLI-Parameter:
```bash
python3 app.py --base-url http://localhost:11524 --api-key DEIN_LOCAL_API_KEY
```
