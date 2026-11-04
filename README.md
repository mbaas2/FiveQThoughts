# FiveQThoughts

Kompakte, plattformübergreifende App (**macOS & Windows**) zum schnellen Sichten, Erstellen, Bearbeiten, Kopieren und Aufräumen der **5 neuesten Quick Thoughts** in **TheBrain 15** über die offizielle lokale REST-API (`/api/v2/quick-thoughts`).

## Features

- **5 neueste Quick Thoughts als Karten**: Liest die Quick-Thoughts-Inbox live über die TheBrain 15 Local API (`GET /api/v2/quick-thoughts` & `GET /api/v2/quick-thoughts/{id}`).
- **⚡ Automatischer Live-Sync**: Prüft alle 5 Sekunden im Hintergrund, ob neue Quick Thoughts eingegangen oder bestehende geändert wurden, und aktualisiert die Karten automatisch (per Schalter **„Live-Sync“** steuerbar).
- **＋ Neue Quick Thoughts anlegen (Taste `N`)**:
  - Erstellt neue Quick Thoughts (`POST /api/v2/quick-thoughts`) mit Markdown-Notiz und optionalen Web-Links.
  - **Grafiken direkt aus der Zwischenablage einfügen**: Einfach im Dialog `⌘V` / `Ctrl+V` drücken oder auf **„🖼️ Grafik aus Clipboard holen“** klicken – wahlweise als Datei-Anhang (`POST /api/v2/quick-thoughts/{id}/files`) oder direkt als Inline-Grafik im Markdown-Text (`![](data:image/...)`).
- **✏️ Vorhandene Quick Thoughts editieren**:
  - Jede Karte besitzt einen **„✏️ Edit“**-Button zum Bearbeiten von Markdown-Text und Links (`PATCH /api/v2/quick-thoughts/{id}`) sowie zum Hinzufügen neuer Grafiken aus dem Clipboard oder Entfernen bestehender Anhänge.
- **Direkte Clipboard-Aktionen pro Karte**:
  - **📋 Text**: Kopiert den Notiztext (bzw. Titel/Links) direkt in die System-Zwischenablage.
  - **🖼️ Grafik**: Kopiert eingebettete oder angehängte Grafiken als echtes Bild (PNG/Bitmap) in die Betriebssystem-Zwischenablage (unter macOS via `osascript`/`sips`, unter Windows via PowerShell `System.Windows.Forms.Clipboard`).
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
