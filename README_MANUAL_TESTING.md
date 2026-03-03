# Manuelles Testen: End-to-End Workflow und Checklisten

Stand: 2026-03-01

Dieses Dokument beschreibt einen realistischen Arbeitsablauf, um moeglichst viele Funktionen in einer Session zu testen und typische Bugs frueh zu finden.

## 1. Ziel

Ziel ist ein reproduzierbarer manueller Test, der folgende Bereiche abdeckt:

- Startverhalten und Autosave-Wiederherstellung
- Draft-Bearbeitung (Tabs, Undo/Redo, Preview, Zoom)
- STT (Whisper-Diktat) und TTS (Vorlesen)
- Import von Dateien und Kontext-Verwaltung
- Markierungen/Highlights inklusive Hover und Jump
- Chat/RAG/Faktencheck (wenn Modell verfuegbar)
- Projekt speichern/laden
- Export (PDF/Word)
- Robustheit bei Fehler- und Abbruchpfaden

## 2. Voraussetzungen

- App startet lokal erfolgreich:
  - `python main.py`
- Optional, aber empfohlen:
  - Mikrofon fuer STT
  - GGUF-Modell fuer Chat/RAG/Faktencheck
  - `python-docx` fuer Word-Export
- Schreibrechte im Projektordner vorhanden

## 3. Testdaten vorbereiten

Nutze vorhandene Dateien im Repo:

- `longtext.md`
- `test.md`
- `prompts/untitled.pdf`
- `prompts/untitled.docx`

Optional:

- Lege eine zusaetzliche TXT-Datei mit Sonderzeichen und langen Zeilen an.
- Lege eine sehr kleine und eine groessere PDF-Datei an (falls vorhanden).

## 4. Testworkflow (vollstaendig)

Hinweis:
- Jede Checkbox aktiv abhaken.
- Bei Fehlern direkt in Abschnitt 8 protokollieren.

### Phase A: Start, Grundzustand, Autosave

- [ ] App starten.
- [ ] Pruefen: Menueleiste zeigt `Einstellungen` mit `Autosave im tmp-Projekt aktivieren`.
- [ ] Autosave EIN schalten (falls aus).
- [ ] Pruefen: `tmp/autosave_project` wird angelegt, sobald erste Aenderung passiert.
- [ ] Neues Draft anlegen (`+ New`), einen Satz schreiben.
- [ ] App schliessen, im Save-Dialog `Discard` waehlen.
- [ ] App erneut starten.
- [ ] Erwartung: Dialog fuer temporaeres Projekt erscheint.
- [ ] Im Dialog `Ja` waehlen.
- [ ] Erwartung: Letzter Zustand ist wieder da.
- [ ] Erneut schliessen, erneut starten, im Dialog diesmal `Nein`.
- [ ] Erwartung: Tmp-Projekt wird verworfen, Session startet ohne den alten Entwurf.

### Phase B: Draft-Editing intensiv

- [ ] In Draft 1 folgenden Text einfuegen:

```text
# Testdokument

Dies ist ein manueller Test.
Absatz zwei mit Zahlen 12345 und Datum 2026-03-01.
- Liste A
- Liste B
```

- [ ] Undo/Redo ueber Toolbar testen.
- [ ] Zweites Draft-Tab anlegen und umbenennen.
- [ ] Tab-Reihenfolge per Drag aendern.
- [ ] Zwischen Tabs wechseln und pruefen, ob Inhalte stabil bleiben.
- [ ] Kontextmenue auf Tab: Read-Only ein/aus testen.
- [ ] View-Modi testen: HTML-only, Markdown-only, beide.
- [ ] Zoom testen:
  - [ ] `Ctrl+=`
  - [ ] `Ctrl+-`
  - [ ] `Ctrl+0`

### Phase C: STT und TTS

STT-Testtext (laut vorlesen):

```text
Hallo, dies ist ein STT Test.
Ich pruefe Zahlen: 7, 42, 1234.
Ich pruefe Satzzeichen: Punkt, Komma, Fragezeichen?
Neue Zeile.
```

- [ ] `AI > Speech Settings...` oeffnen und plausibles Eingabegeraet waehlen.
- [ ] `AI > Start Whisper Dictation` starten.
- [ ] Testtext langsam und klar vorlesen.
- [ ] `AI > Stop Whisper Dictation` ausfuehren.
- [ ] Erwartung: Es wurde ein Transkript-Tab angelegt und Text ist ohne Absturz eingefuegt.
- [ ] TTS testen:
  - [ ] Im Draft auf `Play` klicken.
  - [ ] Stop testen.
  - [ ] Im Chat auf `Vorlesen` (sofern Antwort vorhanden) testen.

### Phase D: Import und Dokumentverwaltung

- [ ] `File > Import Files...` oeffnen.
- [ ] `longtext.md`, `prompts/untitled.pdf`, `prompts/untitled.docx` importieren.
- [ ] Erwartung: Dateien erscheinen im Knowledge-Bereich und im Kontext-Selector.
- [ ] Gleiches Dokument ein zweites Mal importieren.
- [ ] Erwartung: Name wird disambiguiert (z. B. `(1)`).
- [ ] Ein importiertes Dokument wieder entfernen.
- [ ] Erwartung: Aus Dateiliste, Viewer und Chat-Kontext entfernt.

### Phase E: Highlights, Hover, Jump

- [ ] In einem Draft in die HTML-Vorschau wechseln.
- [ ] Textstelle markieren, Rechtsklick, `Markieren (aktueller Tab)` setzen.
- [ ] Zweite Markierung mit anderer Farbe setzen.
- [ ] Hover-Text fuer eine Markierung setzen.
- [ ] Jump-Ziel von Markierung A auf Markierung B setzen.
- [ ] Auf Markierung A klicken, Jump-Verhalten pruefen.
- [ ] Tab umbenennen und pruefen, ob tab-bezogene Markierung weiter funktioniert.
- [ ] Markierung loeschen und pruefen, ob Overlay sofort aktualisiert.
- [ ] View-Menue: `Glossar-Overlay anzeigen` an/aus.

### Phase F: Chat, Rewrite, RAG, Faktencheck (wenn Modell geladen)

- [ ] GGUF-Modell laden.
- [ ] Einfache Chatfrage senden, Streaming/Stop pruefen.
- [ ] Kontextquellen variieren:
  - [ ] nur Draft
  - [ ] nur Dokumente
  - [ ] mit RAG-Ergebnissen
- [ ] Text im Draft selektieren und Rewrite auf Auswahl ausfuehren.
- [ ] Pruefen: Nur selektierter Bereich wurde ersetzt.
- [ ] RAG-Suche im Knowledge-Panel ausfuehren.
- [ ] Faktencheck starten und Ergebnis in neuem Draft oeffnen.

### Phase G: Projekt speichern/laden

- [ ] `File > Save Project...` in neuen Ordner speichern.
- [ ] Mehrere Aenderungen vornehmen (Tabs, Text, Kontextauswahl, Speech-Settings).
- [ ] `File > Load Project...` auf gespeicherten Ordner ausfuehren.
- [ ] Erwartung:
  - [ ] Canvas-Tabs mit Inhalten wiederhergestellt
  - [ ] Importierte Dokumente wieder da
  - [ ] Chat-Historie wieder da
  - [ ] UI-Layout plausibel wiederhergestellt

### Phase H: Export

- [ ] Aktuelles Draft als PDF exportieren.
- [ ] Aktuelles Draft als Word exportieren.
- [ ] Option `Markierungen uebernehmen` testen.
- [ ] Export mit Multi-Column testen.
- [ ] Erwartung: Keine Abstuerze, Datei oeffnet extern und Inhalt passt grob.

### Phase I: Close/Abort/Recovery

- [ ] App schliessen und im Save-Dialog `Cancel` testen.
- [ ] Erwartung: App bleibt offen.
- [ ] App schliessen und `Save` testen.
- [ ] Erwartung: Save-Dialog fuer Projektordner erscheint und Save funktioniert.
- [ ] App waehrend aktiver STT/TTS/LLM-Generation schliessen.
- [ ] Erwartung: Worker werden sauber gestoppt, kein Haengenbleiben.

## 5. Autosave-Spezialtests (Datei-Ebene)

Ziel: pruefen, dass bei Textaenderung nur der betroffene Draft aktualisiert wird.

- [ ] Zwei Draft-Tabs mit Inhalt anlegen.
- [ ] Shell: Zeitstempel notieren:
  - `ls -lah tmp/autosave_project/canvas`
- [ ] Nur in Draft 2 eine kleine Aenderung machen.
- [ ] Nach kurzer Wartezeit (>= 1s) erneut Zeitstempel pruefen.
- [ ] Erwartung: Primaer nur `doc_0001.md` (oder entsprechender Tab-Index) geaendert.
- [ ] Highlight setzen.
- [ ] Erwartung: `highlights.json` wird aktualisiert.
- [ ] Autosave im Menue AUS schalten.
- [ ] Draft erneut aendern.
- [ ] Erwartung: `tmp/autosave_project` wird nicht weiter aktualisiert bzw. entfernt.

## 6. Bug-Hunt Fokus (hohes Risiko)

Gehe diese Punkte gezielt durch:

- [ ] Race Conditions:
  - [ ] Sehr schnell zwischen Tabs wechseln und tippen.
  - [ ] Direkt nach grossen Aenderungen sofort schliessen.
- [ ] Datenverlust:
  - [ ] Mehrfach `Discard`/Neustart mit Autosave-Dialog.
  - [ ] Laden eines alten Projekts nach frischen Aenderungen.
- [ ] UI-Konsistenz:
  - [ ] Read-Only Prefix in Tabs korrekt.
  - [ ] Tab-Titel nach Rename/Load korrekt.
- [ ] Import-Robustheit:
  - [ ] gleiche Datei mehrfach
  - [ ] sehr grosse Datei
  - [ ] nicht unterstuetztes Format
- [ ] Preview/Highlight:
  - [ ] Jump zu geloeschter Markierung
  - [ ] Jump in anderen Tab
  - [ ] Hover-Text mit mehreren Zeilen
- [ ] Worker-Lifecycle:
  - [ ] STT Start/Stop mehrfach hintereinander
  - [ ] LLM-Stop waehrend Streaming

## 7. Quick Smoke (10 Minuten)

Wenn wenig Zeit:

- [ ] Starten, Autosave EIN pruefen.
- [ ] Ein Draft erstellen, Text schreiben, schliessen, wieder oeffnen, Recovery mit `Ja`.
- [ ] Datei importieren.
- [ ] Eine Markierung setzen und wieder loeschen.
- [ ] Projekt speichern und wieder laden.
- [ ] App ohne Fehler beenden.

## 8. Fehlerprotokoll (Template)

Nutze pro Fund ein eigenes Ticket nach diesem Schema:

```text
Titel:
Schweregrad: blocker | high | medium | low
Build/Commit:
OS:
Schritte zur Reproduktion:
1.
2.
3.

Erwartetes Ergebnis:
Tatsaechliches Ergebnis:
Anhang:
- Screenshot/Video
- Logauszug
- betroffene Datei (z. B. tmp/autosave_project/canvas/doc_0001.md)
```

## 9. Exit-Kriterien fuer "Test bestanden"

Mindestens:

- [ ] Kein reproduzierbarer Datenverlust
- [ ] Recovery-Dialog funktioniert in beiden Pfaden (`Ja`/`Nein`)
- [ ] Save/Load Projekt ist stabil
- [ ] STT/TTS verursachen keine Abstuerze
- [ ] Import/Markieren/RAG/Rewrite laufen ohne harte Fehler
- [ ] Keine Blocker- oder High-Bugs offen

