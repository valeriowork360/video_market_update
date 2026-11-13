# Market Pulse: video faceless automatici sulla borsa

Il sistema lavora da solo su GitHub, anche a computer spento.

| Quando | Cosa fa |
|---|---|
| Ogni 4 ore | Controlla i canali in `config.yaml`, analizza i video nuovi (contenuto e **tono dell'autore**) e salva le notizie di mercato |
| Ogni giorno alle 17:43 (ora di Bangkok) | Crea, in **IT** e **EN**: 1 video lungo, 3-7 short e un carosello Instagram per ogni argomento |
| Ogni domenica alle 19:13 | Crea 1 video lungo di recap settimanale e il carosello del recap |

Tutto arriva su **Telegram** per approvazione. La pubblicazione la fai tu.

Costo: 0 €. Usa la chiave API gratuita di Gemini, la voce gratuita Edge TTS, GitHub Actions e un bot Telegram.

---

## Configurazione (circa 20 minuti, una volta sola)

### 1. Chiave Gemini (gratis)
1. Vai su **aistudio.google.com** ed entra con il tuo account Google.
2. Clicca **Get API key** → **Create API key** e copia la chiave.

### 2. Bot Telegram (gratis)
1. Su Telegram apri **@BotFather**, scrivi `/newbot` e scegli un nome. Copia il **token** che ti dà.
2. Apri il tuo bot e premi **Avvia**. Così può scriverti.
3. Apri **@userinfobot** e copia il tuo **Id**: è il tuo chat ID.

### 3. GitHub
1. Crea un account su **github.com**.
2. Crea un repository: **New** → nome `market-pulse` → **Public** → **Create**.
   Scegli *Public* perché così i minuti di calcolo sono illimitati. Con *Private* hai 2.000 minuti al mese e potrebbero non bastare. Le chiavi restano comunque segrete.
3. **Add file → Upload files** e trascina **tutto il contenuto** di questa cartella, compresa la cartella `.github`.
   Su Mac/Windows i file che iniziano con il punto sono nascosti: mostrali prima di trascinarli.
4. **Settings → Secrets and variables → Actions → New repository secret** e aggiungi:
   - `GEMINI_API_KEY`: la chiave del passo 1
   - `TELEGRAM_BOT_TOKEN`: il token del passo 2
   - `TELEGRAM_CHAT_ID`: il tuo Id del passo 2
5. **Settings → Actions → General → Workflow permissions** → scegli **Read and write permissions** → **Save**.

### 4. Controlla i canali
Apri `config.yaml` e verifica gli URL dei canali. Per alcuni ho stimato l'handle (`@Nome`): apri ogni canale su YouTube e copia l'indirizzo esatto.

### 5. Primo avvio manuale
**Actions** → **1 - Raccolta** → **Run workflow**. Al termine:
**Actions** → **2 - Produzione** → **Run workflow**. In 15-30 minuti ricevi tutto su Telegram.

---

## Account X (opzionale)
I post degli account in `x_accounts` (config.yaml) vengono letti tramite **twitterapi.io**
(a pagamento, pochi centesimi al giorno) e filtrati da Gemini: restano solo le parti con
informazioni concrete, mentre promozioni, link a corsi o Discord, giveaway e hype senza dati vengono scartati.
Serve il secret `TWITTERAPI_KEY`. Senza questo secret il passaggio viene saltato e il resto funziona lo stesso.
Puoi rendere il filtro più severo alzando `x_min_score`.

## Personalizzare
In `config.yaml` puoi cambiare:
- `narrator_tone`: `news`, `energetic` o `calm`
- `voices`: la voce narrante
- `brand`: nome e colori del canale
- `daily_minutes`: durata del video lungo
- `shorts_min` / `shorts_max`: quanti short creare

Per cambiare orari: modifica le righe `cron` in `.github/workflows/`. Gli orari sono in UTC, cioè Bangkok meno 7 ore.

## Problemi comuni
- **"trascrizione non disponibile"**: YouTube blocca i server di GitHub. Non è un errore, il sistema passa automaticamente a Gemini, che guarda il video dal link.
- **Errori 429 di Gemini**: hai superato il limite gratuito. Lo script riprova da solo. Se succede spesso, abbassa `max_duration_min`, così salta le live più lunghe.
- **File oltre 50 MB**: Telegram non li accetta. Li scarichi da **Actions → la run → Artifacts**, dove restano 14 giorni.

## Regole che il sistema segue
- Non riusa mai spezzoni dei video degli autori: riassume con parole sue e li cita come fonte. Così eviti strike per copyright.
- Le voci non verificate vengono indicate come "rumor".
- Ogni video chiude con "non è consulenza finanziaria".

## Struttura
```
config.yaml              impostazioni
pipeline/collect.py      raccolta ogni 4 ore
pipeline/write.py        copioni (Gemini)
pipeline/render.py       voce, grafici, slide, montaggio
pipeline/produce.py      produzione giornaliera/settimanale
pipeline/deliver.py      invio su Telegram
data/                    analisi salvate (aggiornate dal bot)
```
Test senza internet:
```
ALLOW_SILENT_TTS=1 python pipeline/produce.py daily --package test/sample_package.json --lang it
```
