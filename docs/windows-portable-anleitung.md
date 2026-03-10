# Windows Portable Anleitung fuer draft2craift

Stand: 2026-03-10

## Ziel

Diese Anleitung beschreibt einen sauberen, reproduzierbaren Weg fuer zwei Rechner:

- Rechner 1: Aus dem Quellcode eine portable Windows-Version bauen.
- Rechner 2: Diese portable Version ohne Python-Installation starten und nutzen.

Das Ziel am Ende ist ein Ordner auf Rechner 2, der mindestens Folgendes enthaelt:

```text
draft2craift-portable\
  draft2craift.exe
  _internal\
  LICENSE
  THIRD_PARTY_NOTICES.md
  start_portable.bat
  models\
    gguf\
    piper\
    whisper\
  hf_cache\
```

Wichtig:

- In diesem Projekt bedeutet "portable" ein kompletter PyInstaller-Ordner, nicht nur eine einzelne `.exe`.
- Du darfst nie nur `draft2craift.exe` allein auf Rechner 2 kopieren. Der ganze Ordner muss zusammenbleiben.
- Wenn du auf Rechner 2 wirklich offline arbeiten willst, musst du auch die benoetigten Modell-Dateien und Caches mitnehmen.

## Was mit dem vorhandenen Build sofort abgedeckt ist

Mit dem vorhandenen Windows-Build-Skript bekommst du einen portablen `onedir`-Build fuer den Kern der App:

- Start der GUI ohne lokale Python-Installation auf Rechner 2
- Markdown-Editor
- Projekt speichern/laden
- GGUF-Chat, wenn du eine lokale `.gguf`-Datei mitnimmst
- RAG/Faktencheck im normalen App-Umfang
- PDF-Import nur mit `-LicenseProfile full`
- DOCX/ODT/HTML-Unterstuetzung gemaess installierten Python-Paketen im Build

## Was zusaetzlich geplant werden muss

Einige Funktionen brauchen mehr als nur die gebaute EXE:

| Funktion | Zusaetzlich noetig |
|---|---|
| Lokaler Chat mit GGUF | Eine oder mehrere `.gguf`-Dateien |
| Piper-TTS | Lokale Piper-Modelle und eine separate `piper`-CLI-Loesung |
| Whisper-STT | Lokale Whisper-Modelle |
| sentence-transformers RAG | Vorab geladener HuggingFace-Cache |
| Transformers-NLI | Zusaetzliche Python-Pakete im Build und vorab geladener HuggingFace-Cache |

Wichtig zu Piper-TTS:

- Der aktuelle Code sucht zur Laufzeit nach einem externen `piper`-Kommando im `PATH`.
- Das ist mit dem Standard-Portable-Build nicht automatisch erledigt.
- Fuer eine wirklich portable TTS-Loesung muss die Verpackung erweitert oder Piper separat bereitgestellt werden.
- Fuer den normalen Portable-Betrieb ist es am einfachsten, Piper-TTS nicht als Muss einzuplanen.

## Empfehlung fuer einen robusten Portable-Build

Wenn dein Ziel "auf Rechner 2 sicher startbar und benutzbar" ist, dann baue zuerst:

- `Variant cpu`
- `LicenseProfile full`

Warum:

- `cpu` laeuft auf fast jedem Windows-Rechner.
- `cuda` ist nur sinnvoll, wenn Rechner 2 eine passende NVIDIA-GPU plus Treiber hat.
- `full` ist noetig, wenn PDF-Import spaeter wirklich funktionieren soll.

## Teil 1: Auf Rechner 1 selbst kompilieren und eine portable EXE erzeugen

### 1. Voraussetzungen auf Rechner 1

Empfohlen:

- Windows 10 oder Windows 11, 64 Bit
- Python 3.11 x64
- PowerShell
- Genug freier Speicherplatz fuer virtuelle Umgebung, Build und Modelle
- Internetzugang fuer die erste Paketinstallation und fuer optionale Modell-Downloads

Optional:

- Git, falls du das Repo klonen willst
- Inno Setup, falls du zusaetzlich einen Installer willst

Hinweise:

- Windows-Builds muessen auf Windows gebaut werden. PyInstaller cross-compiliert hier nicht fuer Windows.
- Wenn du unsicher bist, installiere Python 3.11 x64. Das Build-Skript bevorzugt genau diese Version.

### 2. Quellcode nach Rechner 1 holen

Variante A, mit Git:

```powershell
git clone https://github.com/annuscheit-jonas/draft2craift.git
cd draft2craift
```

Variante B, ohne Git:

- Projektordner als ZIP auf Rechner 1 entpacken
- PowerShell im Projektordner oeffnen

Alle folgenden Befehle werden im Repo-Root ausgefuehrt.

### 3. Standard-Portable-Build erzeugen

Empfohlener Build:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Variant cpu -LicenseProfile full
```

Alternative fuer NVIDIA/CUDA:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Variant cuda -LicenseProfile full
```

Was das Skript macht:

- erstellt eine venv (`.venv-cpu` oder `.venv-cuda`)
- installiert die Basis-Abhaengigkeiten
- installiert die zum Profil passenden optionalen Pakete
- baut mit PyInstaller einen portablen `onedir`-Ordner
- erzeugt zusaetzlich ein ZIP in `dist_portable\`

Erwartete Ergebnisse:

- Build-Ordner: `dist\draft2craift\`
- ZIP-Datei: `dist_portable\draft2craift-FULL-Portable-CPU.zip`

### 4. Was im Buildprofil enthalten ist

Das Skript `packaging\build_windows.ps1` nutzt zwei Profile:

- `-LicenseProfile full`: installiert den kompletten Python-Feature-Stack
  (`sentence-transformers`, `transformers`, `torch`, `faster-whisper`,
  `sounddevice`, `piper-tts`, `onnxruntime`, `pathvalidate`, `pyttsx3`,
  `pymupdf4llm`, `html2text`, `python-docx`, `markdownify`, `odfpy`).
- `-LicenseProfile minimal`: reduziert Extras (kein AGPL/GPL-Importstack,
  keine Speech/NLI-Zusatzpakete).

Wichtig:

- Fuer den Pfad "moeglichst alles soll funktionieren" ist `full` korrekt.
- Piper bleibt trotzdem ein Sonderfall, weil zur Laufzeit ein externes `piper`-Kommando gefunden werden muss.

### 5. Den Build lokal auf Rechner 1 testen

Bevor du irgendetwas auf Rechner 2 kopierst:

```powershell
.\dist\draft2craift\draft2craift.exe
```

Pruefe mindestens:

- App startet
- Ein Draft laesst sich anlegen
- Eine `.md`-Datei laesst sich importieren
- PDF-Import funktioniert, wenn du `-LicenseProfile full` gebaut hast
- DOCX-Export funktioniert

Wenn du lokalen Chat brauchst:

- Lege eine `.gguf`-Datei bereit
- Lade sie in der App ueber `AI > Load GGUF Model...`

### 6. Den finalen portablen Zielordner bauen

Ich empfehle, nicht einfach nur das automatisch erzeugte ZIP weiterzugeben.
Der bessere Weg ist:

1. Den PyInstaller-Ordner als Basis nehmen
2. Deine lokalen Modelle und Caches dazu kopieren
3. Erst danach den finalen Ordner zippen

Beispiel:

```powershell
New-Item -ItemType Directory -Force -Path .\release\draft2craift-portable | Out-Null
Copy-Item -Recurse -Force .\dist\draft2craift\* .\release\draft2craift-portable\
New-Item -ItemType Directory -Force -Path .\release\draft2craift-portable\models\gguf | Out-Null
New-Item -ItemType Directory -Force -Path .\release\draft2craift-portable\models\piper | Out-Null
New-Item -ItemType Directory -Force -Path .\release\draft2craift-portable\models\whisper | Out-Null
New-Item -ItemType Directory -Force -Path .\release\draft2craift-portable\hf_cache | Out-Null
```

Danach kopierst du hinein, was du wirklich brauchst:

- `models\gguf\...` fuer lokale Chat-Modelle
- `models\piper\...` fuer lokale Piper-Modelle
- `models\whisper\...` fuer lokale Whisper-Modelle
- `hf_cache\...` fuer vorab geladene HuggingFace-Modelle

### 7. Empfohlener Start-Launcher fuer den Portable-Ordner

Lege in `release\draft2craift-portable\` eine Datei `start_portable.bat` an:

```bat
@echo off
cd /d "%~dp0"
set "DRAFT2CRAIFT_PIPER_MODELS_DIR=%~dp0models\piper"
set "DRAFT2CRAIFT_WHISPER_MODELS_DIR=%~dp0models\whisper"
set "DRAFT2CRAIFT_TTS_AUTO_DOWNLOAD=0"
set "DRAFT2CRAIFT_STT_AUTO_DOWNLOAD=0"
set "HF_HOME=%~dp0hf_cache"
set "SENTENCE_TRANSFORMERS_HOME=%~dp0hf_cache"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"
"%~dp0draft2craift.exe"
```

Warum diese Datei wichtig ist:

- Sie stellt sicher, dass die App immer aus ihrem eigenen Ordner startet.
- `tmp\autosave_project` landet dann im portablen Ordner und nicht irgendwo anders.
- Whisper- und Piper-Modellordner werden fest an den Portable-Ordner gebunden.
- HuggingFace-Caches koennen lokal im Portable-Ordner gehalten werden.

### 8. GGUF-Modelle portabel mitnehmen

Der Build selbst packt keine `.gguf`-Modelle ein.

Wenn du lokalen Chat, Rewrite oder Teile des Faktenchecks auf Rechner 2 willst:

- kopiere deine `.gguf`-Datei nach `release\draft2craift-portable\models\gguf\`
- starte die App spaeter ueber `start_portable.bat`
- lade das Modell in der App manuell ueber den Dateidialog

Wichtig:

- Projektdateien speichern den Modell-Ladezustand nicht als automatisch geladenes Binary.
- Das GGUF-Modell bleibt daher eine bewusst mitkopierte Zusatzdatei.

### 9. sentence-transformers und NLI fuer Offline-Betrieb vorbereiten

Wenn du auf Rechner 2 auch ohne Internet semantic RAG oder Transformers-NLI nutzen willst, musst du die benoetigten Modelle vorab auf Rechner 1 in den portablen Cache laden.

Praktischer Ablauf:

```powershell
$portable = (Resolve-Path .\release\draft2craift-portable).Path
$env:HF_HOME = "$portable\hf_cache"
$env:SENTENCE_TRANSFORMERS_HOME = "$portable\hf_cache"
$env:HF_HUB_OFFLINE = "0"
$env:TRANSFORMERS_OFFLINE = "0"
$env:DRAFT2CRAIFT_WHISPER_MODELS_DIR = "$portable\models\whisper"
$env:DRAFT2CRAIFT_PIPER_MODELS_DIR = "$portable\models\piper"
& "$portable\draft2craift.exe"
```

Dann in der App:

- sentence-transformers einmal aktivieren/laden
- optional ein NLI-Modell einmal laden

Danach:

- App schliessen
- wieder nur ueber `start_portable.bat` starten

Wichtig:

- Bei `-LicenseProfile full` sind die NLI-Pakete bereits im Build enthalten.
- Fuer echten Offline-Betrieb brauchst du trotzdem den vorab befuellten `hf_cache`.

### 10. Whisper fuer Offline-Betrieb vorbereiten

Die App verwendet fuer STT standardmaessig lokale Whisper-Dateien unter `models\whisper`.

Wenn du Whisper auch auf Rechner 2 offline nutzen willst:

1. Nutze beim Build `-LicenseProfile full`, damit Whisper-Pakete enthalten sind.
2. Starte den portablen Ordner auf Rechner 1 einmal mit gesetztem `DRAFT2CRAIFT_WHISPER_MODELS_DIR`.
3. Lass das benoetigte Whisper-Modell genau einmal herunterladen.
4. Stelle sicher, dass danach Dateien in `release\draft2craift-portable\models\whisper\` liegen.

Ohne diese Vorbereitung wird Whisper auf Rechner 2 entweder nicht verfuegbar sein oder einen Download versuchen.

### 11. Piper-TTS realistisch einordnen

Piper ist im aktuellen Stand der heikelste Teil fuer einen "wirklich portablen" Windows-Ordner.

Grund:

- Der Code ruft zur Laufzeit ein externes `piper`-Kommando auf.
- Der Standard-PyInstaller-Build bundelt dieses externe CLI nicht automatisch als portable Komponente.

Deshalb gilt fuer eine belastbare Anleitung:

- Plane den Portable-Kern nicht von Piper-TTS abhaengig.
- Wenn Piper-TTS zwingend noetig ist, muss die Verpackung technisch erweitert werden.
- Nur das Kopieren von `.onnx`-Modellen reicht fuer Piper-TTS nicht aus, solange kein funktionsfaehiges `piper`-CLI im Zielsystem erreichbar ist.

### 12. Finalen Portable-Ordner als ZIP verpacken

Wenn dein Ordner `release\draft2craift-portable\` komplett ist:

```powershell
if (Test-Path .\release\draft2craift-portable.zip) {
  Remove-Item .\release\draft2craift-portable.zip -Force
}
Compress-Archive -Path .\release\draft2craift-portable -DestinationPath .\release\draft2craift-portable.zip -Force
```

Dieses ZIP ist das, was du an Rechner 2 weitergibst.

## Teil 2: Auf Rechner 2 die portable Version verwenden

### 1. ZIP oder Ordner auf Rechner 2 kopieren

Moegliche Wege:

- USB-Stick
- Netzlaufwerk
- Dateiablage

Empfohlener Zielpfad:

```text
D:\PortableApps\draft2craift-portable\
```

Wichtig:

- Nicht nach `C:\Program Files\` entpacken
- Nicht nur die `draft2craift.exe` einzeln kopieren
- Der Zielordner sollte schreibbar sein

### 2. ZIP vollstaendig entpacken

Nach dem Entpacken sollte mindestens Folgendes sichtbar sein:

```text
draft2craift-portable\
  draft2craift.exe
  _internal\
  LICENSE
  THIRD_PARTY_NOTICES.md
  start_portable.bat
```

Wenn du Zusatzfeatures vorbereitet hast, zusaetzlich:

```text
draft2craift-portable\
  models\
    gguf\
    piper\
    whisper\
  hf_cache\
```

### 3. App auf Rechner 2 starten

Empfohlen:

- `start_portable.bat` doppelklicken

Nicht empfohlen:

- Die EXE aus einer Verknuepfung ohne korrektes "Start in"
- Nur die EXE an einen anderen Ort verschieben

Warum:

- Die Batch-Datei setzt das Arbeitsverzeichnis korrekt.
- Die App findet dadurch portable Modellordner und den lokalen Cache reproduzierbar.

### 4. Erste Funktionspruefung auf Rechner 2

Pruefe direkt nach dem ersten Start:

- App startet ohne Python-Installation
- Neuer Draft laesst sich anlegen
- Import einer `.md`-Datei funktioniert
- PDF-Import funktioniert, wenn du den `full`-Build benutzt hast
- DOCX-Export funktioniert

Wenn du GGUF mitkopiert hast:

- in der App das Modell aus `models\gguf\...` laden
- eine kurze Chat-Anfrage testen

Wenn du `hf_cache` vorbereitet hast:

- sentence-transformers testen
- optional NLI testen

Wenn du `models\whisper` vorbereitet hast (und mit `full` gebaut hast):

- Whisper-Diktat testen

### 5. Was auf Rechner 2 ohne weitere Installation funktionieren sollte

Wenn du den empfohlenen CPU-`full`-Portable-Build sauber vorbereitet hast:

- Start der App
- Schreiben, Speichern, Laden
- Markdown-Arbeit
- Projektdateien
- lokaler GGUF-Chat, wenn `.gguf` mitkopiert wurde
- PDF-Import, wenn `full` gebaut wurde
- DOCX/ODT/HTML gemaess den im Build vorhandenen Paketen

### 6. Was auf Rechner 2 nur unter Zusatzbedingungen funktioniert

Nur wenn vorbereitet:

- sentence-transformers: nur mit lokalem Cache
- Transformers-NLI: nur mit lokalem Cache (bei `full`; bei `minimal` zusaetzliche Pakete noetig)
- Whisper: nur mit lokalem Modell (bei `full`; bei `minimal` zusaetzliche Pakete noetig)
- Piper-TTS: nur mit zusaetzlicher CLI-Loesung, nicht nur mit `.onnx`

## Wichtige praktische Hinweise

### Portable ja, aber nicht komplett spurlos

Die App ist fuer Rechner 2 portable im Sinn von:

- keine Python-Installation noetig
- keine klassische Setup-Installation noetig

Aber:

- Logs werden unter `%USERPROFILE%\.draft2craift\logs\` abgelegt
- UI-Einstellungen werden ueber `QSettings` gespeichert
- Autosave liegt im portablen Ordner, wenn du ueber `start_portable.bat` startest

Das bedeutet:

- "portable" ist hier realistisch portable
- aber nicht "zero traces"

### CPU oder CUDA?

Faustregel:

- Fuer maximale Kompatibilitaet immer `cpu`
- `cuda` nur dann, wenn du sicher weisst, dass Rechner 2 eine passende NVIDIA-Umgebung hat

### `full` oder `minimal`?

Wenn am Ende moeglichst viel funktionieren soll:

- nimm `full`

Wenn du `minimal` baust:

- PDF-Import ist absichtlich reduziert oder nicht verfuegbar
- fuer den hier gewuenschten "alles soll am Ende funktionieren"-Pfad ist `minimal` nicht die richtige Wahl

## Fehlerbilder und schnelle Loesungen

### Die App startet auf Rechner 2 nicht

Pruefen:

- Wurde der komplette Ordner entpackt?
- Ist `_internal\` vorhanden?
- Wird ueber `start_portable.bat` gestartet?

### Chat funktioniert nicht

Pruefen:

- Liegt eine `.gguf`-Datei lokal vor?
- Wurde sie in der App wirklich geladen?
- Bei CPU-Build: `GPU Layers` auf `0` lassen

### PDF-Import fehlt

Ursache:

- Meist wurde nicht `-LicenseProfile full` gebaut.

### sentence-transformers oder NLI wollen Internet

Ursache:

- Modell wurde nicht vorher in `hf_cache\` geladen
- oder die Offline-Umgebungsvariablen werden nicht gesetzt

### Whisper funktioniert nicht

Ursache:

- Speech-Pakete waren beim Build nicht im Bundle
- oder es wurde mit `-LicenseProfile minimal` gebaut
- oder `models\whisper\` ist leer

### Piper-TTS funktioniert nicht

Ursache:

- Ein `.onnx`-Modell allein reicht nicht
- es fehlt die externe `piper`-CLI

## Kurzfassung fuer den schnellsten sauberen Weg

Wenn du den pragmatischsten Weg willst, nimm genau diesen Ablauf:

1. Auf Rechner 1 `cpu + full` bauen:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Variant cpu -LicenseProfile full
```

2. `dist\draft2craift\` nach `release\draft2craift-portable\` kopieren.
3. `start_portable.bat` anlegen.
4. Gewuenschte `.gguf`-Datei nach `models\gguf\` kopieren.
5. Optional `hf_cache\` und `models\whisper\` vorbereiten.
6. Finalen Ordner zippen.
7. Auf Rechner 2 komplett entpacken.
8. Nur ueber `start_portable.bat` starten.

Damit hast du den saubersten Weg zu einem portablen Windows-Ordner, der auf Rechner 2 ohne lokale Python-Installation nutzbar ist.
