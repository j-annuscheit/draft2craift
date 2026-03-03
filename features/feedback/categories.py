"""Standard error categories per use-case (Deutsch)."""

CATEGORIES: dict[str, list[str]] = {
    "chat_answer": [
        "Fehlende Wörter im Satz",
        "Sätze beginnen immer gleich",
        "Falsche Informationen",
        "Zu lange Antwort",
        "Zu kurze Antwort",
        "Schlechter Schreibstil",
        "Antwort thematisch falsch",
        "Sonstiges",
    ],
    "fact_check": [
        "Fakten falsch bewertet",
        "Quellen falsch zugeordnet",
        "Ergebnis unvollständig",
        "Zu viele Falsch-Positive",
        "Sonstiges",
    ],
    "canvas_edit": [
        "Rewrite inhaltlich falsch",
        "Wichtige Aussagen fehlen",
        "Zu stark verändert",
        "Schlechter Schreibstil",
        "Sonstiges",
    ],
    "mindmap": [
        "Knotenstruktur unklar",
        "Wichtige Knoten fehlen",
        "Verbindungen fehlerhaft",
        "Interaktion/Navigation problematisch",
        "Sonstiges",
    ],
    "rag_search": [
        "Falsche Dokumente gefunden",
        "Relevante Dokumente fehlen",
        "Ergebnisse doppelt",
        "Schlechte Relevanz",
        "Sonstiges",
    ],
    "file_import": [
        "Text unlesbar/fehlerhaft",
        "Formatierung verloren",
        "Seiten/Abschnitte fehlen",
        "Tabellen fehlerhaft",
        "Zu viel Rauschen",
        "Sonstiges",
    ],
}

DEFAULT_CATEGORIES: list[str] = [
    "Fehlerhafte Ausgabe",
    "Unerwartetes Verhalten",
    "Sonstiges",
]
