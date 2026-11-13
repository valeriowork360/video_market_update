# Market Pulse

Un canale faceless di notizie di borsa, in italiano e in inglese, che si produce da solo.
Gira gratis su GitHub, anche a computer spento. Tu ricevi tutto su Telegram, approvi e pubblichi.

## Cosa fa

| Quando | Cosa succede |
|---|---|
| Ogni 4 ore | Guarda i video nuovi degli 8 canali, scrive per ognuno **cosa dice l'autore e con che tono**, salva le notizie di mercato. Ti manda su Telegram il riassunto di ogni video nuovo. |
| Ogni giorno, 17:43 (Bangkok) | Per ogni lingua: **1 video lungo**, **3-7 short** ricavati da quel video, **1 carosello Instagram per argomento**, miniatura, titolo, descrizione e tag. |
| Domenica, 19:13 | **Video lungo di riepilogo** della settimana e **carosello di riepilogo**. |

Il tono della voce narrante viene scelto ogni giorno in base al mercato (pacato, da telegiornale, incalzante, energico).
I video che riguardano solo l'Italia (per esempio le tasse italiane di Marco Casario) entrano nell'edizione italiana e restano fuori da quella inglese.

## Come si usa

Non devi fare nulla: parte da solo. Per avviarlo a mano apri **Actions** su GitHub, scegli la voce e premi **Run workflow**:

- **0 - Controllo**: prova chiavi, AI, feed, voce e prezzi, e ti manda il referto su Telegram. Usalo se qualcosa non torna.
- **1 - Raccolta**: analizza subito i video nuovi.
- **2 - Produzione**: crea subito il giornaliero (o il settimanale). Con *force* lo rifà anche se già consegnato. Con *silent* fa una prova senza inviare nulla su Telegram: i file restano negli Artifacts della run.

## Perché adesso regge

La versione precedente non ha mai consegnato un video. I motivi, e cosa è cambiato:

- **Quota Gemini.** Il piano gratuito concede circa 20 richieste al giorno ai modelli *flash* e circa 500 ai modelli *flash-lite*. Prima si usava *flash* per tutto e la quota finiva con la raccolta. Ora *flash-lite* guarda i video e *flash* resta libero per i copioni (ne servono 4 al giorno).
- **Riserve vere.** Se un modello è sovraccarico (errore 503) o ha finito la quota (429) si passa subito al successivo: 3.8, 3.6, poi i *lite*, poi le AI di riserva. I nomi dei modelli vengono letti da Google a ogni giro, quindi un cambio di nome non rompe nulla.
- **Niente si perde.** Un video che non si riesce ad analizzare resta in coda per il giro dopo. La produzione salva ogni passaggio: se si ferma, due riprese automatiche (20:43 e 23:13) completano solo quello che manca. Quello che è pronto ti arriva subito.
- **Video nuovi da due fonti.** I feed RSS di YouTube dai server GitHub spesso non rispondono: ora i video nuovi si leggono anche dalle pagine dei canali, e basta che una delle due fonti funzioni.
- **Video lunghi.** Vengono letti a pezzi da 40 minuti e con pochi fotogrammi (conta l'audio), così restano dentro i limiti gratuiti.
- **Numeri verificati.** I prezzi arrivano da Yahoo Finance e l'AI può citare solo quelli. Le voci non confermate vengono chiamate "rumor". Promozioni, sponsor e clickbait degli autori vengono scartati.

## Chiavi (Settings > Secrets and variables > Actions)

| Segreto | A cosa serve | |
|---|---|---|
| `GEMINI_API_KEY` | Guarda i video e scrive i copioni | già presente |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Consegna su Telegram | già presenti |
| `MISTRAL_API_KEY` | AI di riserva per i copioni (gratis su console.mistral.ai) | facoltativo, consigliato |
| `GROQ_API_KEY` | Altra AI di riserva (gratis su console.groq.com) | facoltativo |

Le riserve entrano in gioco solo se tutti i modelli Gemini sono occupati. Basta aggiungere il segreto: nessun'altra modifica.

## Impostazioni

Tutto in `config.yaml`: canali, feed di notizie, lunghezza dei video, numero di short, voci, colori e nome del canale.
Per cambiare gli orari modifica le righe `cron` in `.github/workflows/2-produce.yml` (sono in UTC: Bangkok meno 7 ore).

## Account X

Per ora spenti: X non offre più un accesso gratuito per leggere i post. L'elenco degli account è già in `config.yaml`, pronto per quando lo attiveremo con il filtro anti-clickbait.

## Se qualcosa non va

- **Messaggio "produzione incompleta"**: non serve fare nulla, viene ritentata da sola. Se a fine giornata manca ancora, avvia *0 - Controllo*.
- **Video senza grafici**: Yahoo Finance non ha risposto in quel momento. Il video esce lo stesso.
- **File oltre 50 MB**: Telegram non lo accetta; lo trovi in Actions > la run > Artifacts (14 giorni).
- **Un autore manca**: guarda il riassunto della raccolta su Telegram; i video non di mercato vengono esclusi apposta.

## Struttura

```
config.yaml          impostazioni
mp/collect.py        raccolta ogni 4 ore (coda, tentativi, riassunto su Telegram)
mp/youtube.py        video nuovi dei canali (pagine + RSS)
mp/watch.py          da video a nota: contenuto, tono, previsioni, rumor
mp/llm.py            scelta del modello, riserve, rispetto delle quote
mp/news.py           notizie RSS, prezzi verificati, calendario economico
mp/writer.py         copione lungo, poi short e caroselli ricavati dal copione
mp/tts.py            voce (Edge TTS, riserva gTTS) con tempi delle parole
mp/draw.py           grafica di video, short, caroselli, miniatura
mp/video.py          montaggio con ffmpeg
mp/produce.py        produzione giornaliera e settimanale, a tappe
mp/doctor.py         controllo generale
data/                note, notizie, copioni e stato (aggiornati dal bot)
```

Prove senza internet:

```
python -m tests.test_logic
MP_FAKE_TTS=1 MP_FAKE_PRICES=1 python -m mp.produce daily --offline
```

Regole che il sistema segue: non riusa mai spezzoni dei video degli autori, li cita come fonte e riassume con parole sue; ogni video chiude con "non è consulenza finanziaria".
