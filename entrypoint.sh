#!/bin/sh -l

# Przekaż wszystkie argumenty wejściowe bezpośrednio do skryptu analizatora Pythona.
# "$@" rozszerza się do listy wszystkich argumentów pozycyjnych, z których każdy jest cytowany.
python /app/analyzer.py "$@"