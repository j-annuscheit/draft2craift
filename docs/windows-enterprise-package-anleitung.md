# Windows Enterprise Package Anleitung (alle Features)

Stand: 2026-03-10

## Ziel

Diese zweite Anleitung beschreibt nicht den portablen Ordner, sondern einen
installierbaren Windows-Build fuer Unternehmensverteilung (z. B. Intune, SCCM,
baramundi, Matrix42, Ivanti, PDQ).

Zielbild:

- zentrale, silent-faehige Installation
- unter Windows laufen alle App-Features
- reproduzierbar fuer viele Clients

## Wichtig vorab

"Alle Features laufen" bedeutet in diesem Projekt:

1. `LicenseProfile full` beim Build
2. zusaetzliche Runtime-Assets im Deployment:
   - GGUF-Modell(e)
   - Whisper-Modelle
   - HuggingFace-Cache fuer sentence-transformers / NLI
   - externe Piper-CLI (nicht nur Python-Paket)

Ohne diese Assets ist die App installierbar, aber einzelne Funktionen bleiben
eingeschraenkt.

## 1. Empfohlene Paketstrategie

Empfohlen sind zwei Pakete:

1. **App-Paket**: Installer fuer `draft2craift` (CPU-full).
2. **Assets-Paket**: Modelle, HF-Cache, Piper-CLI, Launcher.

Warum diese Trennung:

- App-Updates sind klein und haeufig.
- Modell-/Cache-Pakete sind gross und aendern selten.
- Deployment-Systeme koennen Abhaengigkeiten sauber steuern.

Wenn gewuenscht, kann auch ein einziges grosses Gesamtpaket gebaut werden.

## 2. Build des installierbaren App-Pakets

Auf einem Windows-Build-Host:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Variant cpu -LicenseProfile full
```

Ergebnis:

- `dist\draft2craift\` (PyInstaller onedir)
- `dist_installer\draft2craift-FULL-Setup-CPU.exe` (wenn Inno Setup `iscc` vorhanden)

Hinweis:

- Fuer breiteste Kompatibilitaet im Unternehmen `cpu` verwenden.
- Optional zusaetzlich CUDA-Build fuer dedizierte GPU-Clientgruppe.

## 3. Full-Feature Runtime-Assets bereitstellen

Lege einen zentralen Asset-Pfad fest, z. B.:

```text
C:\ProgramData\draft2craift\
  models\
    gguf\
    whisper\
    piper\
  hf_cache\
  tools\
    piper\
```

### 3.1 GGUF

- mindestens ein freigegebenes `.gguf`-Modell nach
  `C:\ProgramData\draft2craift\models\gguf\`.

### 3.2 Whisper

- benoetigte Whisper-Modelle nach
  `C:\ProgramData\draft2craift\models\whisper\`.
- alternativ einmal online vorladen und danach als Paket verteilen.

### 3.3 sentence-transformers + NLI (offline-faehig)

- benoetigte HF-Modelle in
  `C:\ProgramData\draft2craift\hf_cache\` vorab ablegen.
- so vermeiden Clients Internetzugriffe zur Laufzeit.

### 3.4 Piper-TTS

Wichtig:

- Der Code ruft ein externes `piper`-Kommando auf.
- `piper-tts` als Python-Paket allein reicht dafuer im installierten Bundle
  nicht aus.

Daher:

- eine **native Windows Piper-CLI Distribution** komplett nach
  `C:\ProgramData\draft2craift\tools\piper\` legen
  (inkl. benoetigter DLLs/Runtime-Dateien).
- Piper-Modelle (`.onnx` + `.onnx.json`) nach
  `C:\ProgramData\draft2craift\models\piper\`.

## 4. Enterprise Launcher (empfohlen)

Erzeuge auf dem Zielsystem einen Launcher, z. B.
`C:\Program Files\draft2craift\start_enterprise.cmd`:

```bat
@echo off
setlocal
set "D2C_ROOT=C:\ProgramData\draft2craift"
set "DRAFT2CRAIFT_PIPER_MODELS_DIR=%D2C_ROOT%\models\piper"
set "DRAFT2CRAIFT_WHISPER_MODELS_DIR=%D2C_ROOT%\models\whisper"
set "HF_HOME=%D2C_ROOT%\hf_cache"
set "SENTENCE_TRANSFORMERS_HOME=%D2C_ROOT%\hf_cache"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"
set "DRAFT2CRAIFT_TTS_AUTO_DOWNLOAD=0"
set "DRAFT2CRAIFT_STT_AUTO_DOWNLOAD=0"
set "PATH=%D2C_ROOT%\tools\piper;%PATH%"
start "" "%~dp0draft2craift.exe"
endlocal
```

Warum Launcher:

- fixe Pfade fuer Modelle/Caches
- keine Schreibzugriffe in `Program Files` noetig
- Piper-CLI wird ueber `PATH` sicher gefunden
- reproduzierbares Verhalten fuer alle Benutzer

## 5. Inno-Installer silent im Unternehmenssystem

Installationsbefehl:

```powershell
draft2craift-FULL-Setup-CPU.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
```

Deinstallationsbefehl:

```powershell
"C:\Program Files\draft2craift\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Empfohlene Detection Rule:

- Datei existiert:
  `C:\Program Files\draft2craift\draft2craift.exe`

Optional zusaetzlich:

- Dateiversion pruefen
- Registry-Uninstall-Key pruefen (`...Uninstall\..._is1`)

## 6. Beispiel Deployment-Reihenfolge

1. App-Paket installieren (silent).
2. Asset-Paket nach `C:\ProgramData\draft2craift\` kopieren.
3. Launcher `start_enterprise.cmd` ausrollen.
4. Startmenu/Desktop-Verknuepfung auf Launcher setzen (nicht direkt auf `.exe`).
5. Smoke-Test pro Zielgruppe.

## 7. Smoke-Test "alle Features"

Auf einem frisch installierten Client testen:

1. App startet ueber Launcher.
2. PDF/DOCX/HTML/ODT Import funktioniert.
3. GGUF laden und Chat-Antwort erzeugen.
4. RAG mit sentence-transformers aktivieren.
5. Fact-Check mit NLI-Backend testen.
6. Whisper-Diktat starten/stoppen.
7. Piper-TTS abspielen.
8. Projekt speichern/laden.

Erst nach bestandenem Smoke-Test breit ausrollen.

## 8. Bekannte Stolpersteine

1. **Piper geht nicht**
   Ursache: `piper`-CLI fehlt in `PATH` oder unvollstaendig verteilt.

2. **Whisper/NLI wollen Internet**
   Ursache: Cache nicht vorab verteilt oder Launcher/Offline-Flags fehlen.

3. **Modelldownload scheitert**
   Ursache: Schreibrechte fehlen (z. B. nur `Program Files` genutzt).

4. **Mikrofon-Features ohne Funktion**
   Ursache: Endpoint Policy / Treiber / Device-Freigaben, nicht primar App-Paket.

## 9. Sicherheit und Compliance

1. Installer und ggf. Wrapper signieren (Authenticode).
2. Hashes der Modelle/Assets dokumentieren.
3. Lizenzfreigaben fuer Full-Profil (AGPL/GPL-Anteile) intern klaeren.
4. Rollout in Ringen (Pilot -> Welle 1 -> Welle 2).

## 10. Kurzfazit

Ja, eine voll installierbare Enterprise-Version mit allen Features ist unter
Windows umsetzbar.

Der entscheidende Punkt ist:

- nicht nur die App installieren,
- sondern das Runtime-Asset-Bundle (Modelle/Cache/Piper-CLI) plus Launcher
  kontrolliert mit ausrollen.
