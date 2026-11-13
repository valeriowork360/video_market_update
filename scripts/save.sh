#!/usr/bin/env bash
# Salva la cartella data/ nel repository, riprovando se nel frattempo e' cambiato qualcosa.
set -u
git config user.name "market-pulse-bot"
git config user.email "market-pulse-bot@users.noreply.github.com"
git add -A data
if git diff --cached --quiet; then echo "Niente di nuovo da salvare"; exit 0; fi
git commit -q -m "$1"
for i in 1 2 3 4 5; do
  if git pull -q --rebase origin main && git push -q origin HEAD:main; then echo "Dati salvati"; exit 0; fi
  git rebase --abort 2>/dev/null || true
  sleep $((i * 7))
done
echo "::warning::Salvataggio dei dati non riuscito"
exit 1
