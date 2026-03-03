## API-Sicherheit und Zugriffskontrollen

Fehlende Rollenprüfung in API-Endpunkten führt häufig dazu, dass Nutzer auf Daten
zugreifen können, die nicht für sie bestimmt sind. Ein zweites Problem ist
Token-Leakage, etwa durch unsichere Log-Ausgaben oder falsch konfigurierte Clients.

Empfohlen werden kurze Token-Laufzeiten, starke Segmentierung, und ein
Zero-Trust-Ansatz für interne sowie externe Dienste.
