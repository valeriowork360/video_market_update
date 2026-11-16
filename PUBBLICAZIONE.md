# Pubblicazione automatica: cosa serve

Il codice è già pronto. Per accendere una piattaforma basta aggiungere le sue chiavi tra i segreti
di GitHub: da quel momento il sistema pubblica da solo, senza altre modifiche.
Un account per lingua: le chiavi finiscono con `_IT` o `_EN`.

Dove si aggiungono i segreti: GitHub > repository > **Settings > Secrets and variables > Actions > New repository secret**.

Per verificare: **Actions > 0 - Controllo > Run workflow > cosa: pubblicazione**. Il referto arriva su Telegram in un minuto e non consuma quota AI.

| Piattaforma | Stato | Cosa pubblica |
|---|---|---|
| Instagram | Funziona appena aggiungi il token | 3 Reel e 2 caroselli al giorno per account (i più forti; il resto arriva comunque su Telegram) |
| YouTube | Pronto, ma serve prima l'approvazione di Google | Video lungo e 3 Shorts al giorno per canale |
| TikTok | Non automatizzabile gratis, vedi sotto | Gli short continuano ad arrivare su Telegram |

I numeri al giorno si cambiano in `config.yaml`, sezione `publish`.

---

## 1. Instagram (si può fare subito)

**Account**
1. Crea i due account Instagram (italiano e inglese).
2. In ognuno: Impostazioni > Tipo di account > **Passa a un account professionale** (Creator o Business). Con un account personale l'API non funziona.

**App Meta** (una sola, vale per entrambi gli account)
1. Vai su developers.facebook.com, accedi con un account Facebook e registrati come sviluppatore.
2. **Crea app** e scegli il caso d'uso che riguarda Instagram (gestione di messaggi e contenuti).
3. Nel menu dell'app apri **Instagram > Configurazione API con accesso tramite Instagram**.
4. In **Genera token di accesso** aggiungi il primo account Instagram, accedi e consenti. Devono essere attive le autorizzazioni `instagram_business_basic` e `instagram_business_content_publish`.
5. Premi **Genera token** e copialo subito: viene mostrato una volta sola.
6. Ripeti i punti 4 e 5 con il secondo account.

**Segreti da aggiungere su GitHub**
- `IG_TOKEN_IT`: token dell'account italiano
- `IG_TOKEN_EN`: token dell'account inglese

Il token dura 60 giorni, ma il sistema lo rinnova da solo ogni settimana. Se un giorno il rinnovo non riesce ti arriva un avviso su Telegram.

Per un account tuo non serve la revisione dell'app da parte di Meta. I nomi dei menu sulla pagina di Meta cambiano spesso: se non trovi una voce, mandami una schermata.

---

## 2. YouTube (serve l'approvazione di Google)

Google tiene **privato per sempre** ogni video caricato via API da un progetto che non ha superato il suo controllo ("audit"). Per questo il caricamento è spento (`mode: "off"` in `config.yaml`) finché l'audit non passa: un video caricato prima non si potrebbe più rendere pubblico, nemmeno a mano.

**Canali**
1. Con un solo account Google crea due canali YouTube (italiano e inglese).

**Progetto Google**
1. Vai su console.cloud.google.com e crea un progetto.
2. **API e servizi > Libreria**: attiva **YouTube Data API v3**.
3. **Schermata di consenso OAuth**: tipo *Esterno*, poi porta lo stato di pubblicazione su **In produzione** (in stato "Test" l'accesso scade ogni 7 giorni).
4. **Credenziali > Crea credenziali > ID client OAuth**, tipo *Applicazione web*, con URI di reindirizzamento `https://developers.google.com/oauthplayground`. Copia ID client e segreto client.

**Accesso ai due canali**
1. Apri developers.google.com/oauthplayground, clicca l'ingranaggio, spunta **Use your own OAuth credentials** e incolla ID client e segreto.
2. Nel campo degli ambiti scrivi: `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly`
3. **Authorize APIs**, scegli il canale italiano, poi **Exchange authorization code for tokens**. Copia il *Refresh token*.
4. Ripeti il punto 3 scegliendo il canale inglese.

**Segreti da aggiungere su GitHub**
- `YT_CLIENT_ID`, `YT_CLIENT_SECRET`
- `YT_REFRESH_TOKEN_IT`, `YT_REFRESH_TOKEN_EN`

**Richiesta di audit**
Si chiede con il modulo *YouTube API Services - Audit and Quota Extension Form*. Quando hai creato il progetto dimmelo: ti preparo io le risposte del modulo. I tempi li decide Google e l'esito non è garantito.

Quando Google approva, in `config.yaml` cambia `mode: "off"` in `mode: "public"`. Fino ad allora il video lungo e gli Shorts li pubblichi a mano dai file che arrivano su Telegram.

---

## 3. TikTok (non automatizzabile con le API gratuite)

TikTok lascia visibili solo all'autore i video pubblicati da un'app che non ha superato il suo controllo, e per superarlo chiede un'app con schermate per l'utente (scelta della privacy, consenso, anteprima) che un sistema automatico senza interfaccia non ha. Una richiesta fatta per questo progetto verrebbe con ogni probabilità respinta, quindi non l'ho costruita.

Le strade realistiche sono due:
- continuare a pubblicare a mano gli short che arrivano su Telegram;
- usare un servizio di pubblicazione con app già approvata (a pagamento, circa 24-29 $ al mese) solo per TikTok.

---

## Spegnere tutto

In `config.yaml`: `publish: enabled: false`. I contenuti continuano ad arrivare su Telegram.
