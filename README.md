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
- **🖥️ Eigenständige Desktop-App & Systemweiter Shortcut (`⌃⌥Q` / `Ctrl+Alt+Q`)**:
  - **macOS (`FiveQThoughts.app`)**: Kompiliert beim ersten Start aus `native/macos_host.swift` automatisch eine leichtgewichtige native macOS-App (System-`WKWebView`, ~110 KB Binary). Erscheint als **eigenständige App mit Blitz-Icon in `⌘+Tab` und im Dock** sowie als Menüleistensymbol **`⚡5Q`**.
  - **Windows (`FiveQThoughts.exe`, installierbar)**: Nativer Host aus `native/windows/` (WinForms + eingebettetes **WebView2**, das Windows-Gegenstück zu `WKWebView`). Eigenes Fenster mit Blitz-Icon in Taskleiste und `Alt+Tab`, **System-Tray-Icon** (Linksklick = ein-/ausblenden, Rechtsklick = Menü mit *Aktualisieren*, *Im Browser öffnen*, *Mit Windows starten*, *Beenden*), Schließen per `X`/`Ctrl+W` blendet nur ins Tray aus, ein zweiter Start holt das laufende Fenster nach vorn. Der **Installer** (`FiveQThoughts-Setup-x.y.z.exe`) bringt ein gebündeltes Python-Backend mit – auf dem Zielrechner wird **kein Python** benötigt.
  - **Globaler Shortcut**: Mit **`⌃⌥Q`** (`Ctrl+Option+Q` auf macOS) bzw. **`Ctrl+Alt+Q`** (auf Windows) lässt sich das Fenster jederzeit systemweit aus jeder anderen Anwendung heraus in den Vordergrund holen oder wieder ausblenden.
  - **☁️ Automatischer Cloud-Fallback (TheBrain Web-API `api.bra.in`)**: Funktioniert auch, wenn die lokale Desktop-App gerade nicht geöffnet ist! Standardmäßig wird die blitzschnelle lokale Instanz (`http://localhost:11524`) genutzt. Ist TheBrain lokal nicht erreichbar, schaltet FiveQThoughts vollautomatisch auf die offizielle Cloud-API (`https://api.bra.in/v2/...`) um (einstellbar unter `⚙ API` mit Cloud-Key von [app.thebrain.com/api-keys](https://app.thebrain.com/api-keys)). Ein Badge in der Kopfzeile zeigt den aktuellen Status (`💻 Lokal` / `☁️ Cloud`).
  - **🌓 Light & Dark Mode (Hell / Dunkel)**: Unterstützt sowohl ein elegantes, kontrastreiches helles Design (Light Mode) als auch ein augenschonendes dunkles Design (Dark Mode). Erkennt die macOS/Windows-Systemeinstellung automatisch oder lässt sich per Schnellschalter `🌗` in der Kopfzeile sowie im Einstellungsmenü jederzeit manuell auf *Automatisch*, *Hell* oder *Dunkel* umschalten.
  - **📐 Vollflächiges, dynamisches Kachel-Raster (Gleich große Kacheln)**: Nutzt die volle Breite und Höhe des Fensters optimal aus (keine starre Breitenbegrenzung mehr). Alle konfigurierten Quick-Thought-Kacheln haben exakt dieselbe Größe. Bei jeder Änderung der Fenstergröße passt sich die Rasteraufteilung (z. B. 3×2, 2×3, einspaltig) in Echtzeit fließend an, während lange Texte oder Bildersammlungen sauber innerhalb der jeweiligen Kachel scrollen.
  - **🌍 Mehrsprachigkeit (i18n JSON)**: Vollständig lokalisiert in **Deutsch** (`static/i18n/de.json`) und **Englisch** (`static/i18n/en.json`). Erkennt beim Start automatisch die Systemsprache (`de` oder `en`, Fallback `en`) und erlaubt jederzeit den direkten Sprachwechsel in der Kopfzeile (`🇩🇪 DE` / `🇬🇧 EN`) oder in den Einstellungen.
  - **Versionierung**: Die aktuelle SemVer-Version wird zentral in der Datei [`VERSION`](./VERSION) gepflegt und in der UI, im macOS-Bundle sowie im Backend ausgewiesen.

## Voraussetzungen

- **TheBrain 15** (lokal installiert) und/oder ein Account auf **TheBrain Cloud** ([app.thebrain.com](https://app.thebrain.com)).
- **API Key**:
  - Für lokale Nutzung: **Local API Key** aus **TheBrain 15 → Settings → User → Local API**.
  - Für Cloud-Fallback (wenn TheBrain Desktop nicht läuft): **Cloud API Key** aus [app.thebrain.com/api-keys](https://app.thebrain.com/api-keys).
- **Python 3.9+** (auf macOS und Windows ohne `pip install` direkt lauffähig).

## Starten

### macOS
Per Doppelklick auf `run_mac.command` im Finder oder im Terminal:
```bash
python3 app.py
```

### Windows – installierte App (empfohlen)
`dist\FiveQThoughts-Setup-<version>.exe` ausführen. Installiert standardmäßig nur für den aktuellen Benutzer (keine Admin-Rechte nötig) nach `%LOCALAPPDATA%\Programs\FiveQThoughts`, mit Startmenü-Eintrag, optionalem Desktop-Symbol und optionalem Autostart (startet unsichtbar im Tray). Deinstallation über *Einstellungen → Apps*.

Alternativ ohne Installation: `dist\FiveQThoughts-<version>-win-x64-portable.zip` entpacken und `FiveQThoughts.exe` starten.

Daten der installierten App:
- Konfiguration inkl. API-Keys: `%APPDATA%\FiveQThoughts\config.local.json` (bleibt bei Deinstallation erhalten)
- WebView2-Cache, Fensterposition, `backend.log`: `%LOCALAPPDATA%\FiveQThoughts`

Voraussetzung ist nur die **Microsoft Edge WebView2 Runtime** (in Windows 11 enthalten; fehlt sie, bietet die App den Download an).

### Windows – aus dem Quellcode
Per Doppelklick auf `run_windows.bat` (baut beim ersten Start den Host mit dem .NET SDK und startet ihn mit `app.py` als Backend) oder in PowerShell / CMD:
```powershell
python app.py
```
Ohne .NET SDK öffnet `app.py` die Oberfläche als Edge/Chrome-App-Fenster (Shortcut `Ctrl+Alt+Q` funktioniert auch dann).

### Windows-Installer bauen
Benötigt auf dem Build-Rechner: .NET SDK 8+, Python 3.9+ und [Inno Setup 6](https://jrsoftware.org/isdl.php).
```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```
Ergebnis in `dist\`: `FiveQThoughts-Setup-<version>.exe` und die portable ZIP. Das Skript baut den Host (`native\windows`), bündelt `app.py` + `static\` per PyInstaller (eigenes venv unter `build\.venv`) und erstellt den Installer aus `packaging\windows\FiveQThoughts.iss`. Die Version kommt aus der Datei `VERSION`. Das App-Icon (`native\windows\FiveQThoughts.ico`) lässt sich mit `native\windows\make_icon.ps1` neu erzeugen.
