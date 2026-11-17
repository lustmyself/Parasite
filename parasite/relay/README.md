# Parasite parti relay'i (Cloudflare Worker)

Parasite kullanıcılarının birbirinin skinini gördüğü sunucu (`launcher/parasite_share.py`,
`party/network/ws_relay.py`). Kod: `src/index.ts` (yönlendirme), `src/room.ts` (oda, Durable
Object `PartyRoom`), `src/directory.ts` (LoL arkadaş dizini, Durable Object `FriendsDirectory`).

Parasite build'leri, Cloudflare secret'ları yoksa (`write_config.py`) Lust'ın relay'ini kullanır:
`wss://lust-party-relay.nysperado.workers.dev`. Aynı relay'i Lust, Parasite ≤ 2.10 ve Parasite
2.11+ birlikte kullanır; bu kod hepsine aynı anda hizmet eder.

## Protokoller

| İstemci | Protokol | Nasıl tanınır | Ne görür |
|---|---|---|---|
| Lust (1.4.9.x) | 1 | URL'de `p` yok, `join` mesajı | Odadaki herkesi (1 ve 2) |
| Parasite ≤ 2.10 | 1 | URL'de `p` yok, `join` mesajı | Odadaki herkesi (1 ve 2) |
| Parasite 2.11+ (Rose 1.5.7) | 2 | `p=2`, kimlik header'larda | Sadece protokol 2 üyeleri |

Protokol 2 (Rose 1.5.7'den, Parasite adlarıyla):

- İstemci gönderir: `/room?key=<32 hex>&v=<sürüm>&p=2`, `X-Parasite-Summoner-Id` (ondalık, 64 bit),
  `X-Parasite-Summoner-Name` (URL-encoded), `Authorization: Bearer <64 hex>` (kurulumun relay
  adresine özel HMAC'i).
- Relay cevaplar: `101` + `X-Parasite-Party-Protocol: 2` (istemci bu header'ı görmezse bağlantıyı
  kapatır ve parti modunu durdurur). Üye listesinde `summoner_id` metin, her üyede `member_key`
  (credential'ın SHA-256'sı) vardır; `member_key`'i olmayan üyeyi istemci atar.
- Bağlı bir üyenin ID'sini sadece aynı kurulum alabilir; başka kurulum `403` alır. Üye çıkınca ID
  serbest kalır (yeniden kurulum, başka PC).
- `X-Lust-*` ve `X-Rose-*` header'ları da kabul edilir; cevap header'ı aynı önekle gelir. Bugün
  bunları gönderen istemci yok (Lust ve Parasite ≤ 2.10 header göndermez, protokol 1 kullanır),
  ama Lust ileride Rose 1.5.7'ye geçerse `X-Lust-*` ile çalışır.

### Karışık odalar (protokol 1 + 2 aynı odada)

İki protokol aynı oda nesnesini paylaşır (oda adı eskisi gibi `key`).

- Protokol 1 (Lust, Parasite ≤ 2.10) herkesi görür: protokol 2 üyeleri ona sayısal `summoner_id`
  ile gider (64 bit ID'ler de bozulmadan).
- Protokol 2 (Parasite 2.11+) sadece protokol 2 üyelerini görür: protokol 1'in kimliği
  doğrulanmaz ve 2.11 istemcisi `member_key`'siz üyeyi zaten atar. Yani 2.10 kullanıcısı 2.11
  arkadaşının skinini görür, tersi olmaz (2.10 otomatik güncellenince düzelir).
- Protokol 1'in, bağlı bir protokol 2 üyesinin ID'siyle `join`'i yok sayılır (o bağlantı odada kalır
  ama listelenmez).
- Aynı oyuncu protokol 2 ile gelirse eski protokol 1 bağlantısının yerini alır (güncellemiş).
- Oda en fazla 10 bağlantı alır, iki protokol birlikte sayılır.

## Test

```bash
cd parasite/relay
npm ci
npx tsc --noEmit
npm test                      # workerd'de gerçek WebSocket'lerle protokol 1, 2 ve karışık oda
npx wrangler deploy --dry-run # paketlenebiliyor mu (hiçbir şey yüklemez)
```

## Lust'ın relay'ine (`lust-party-relay`) kurulum

**Önemli:** Parasite 2.11 bu kod kurulmadan çıkarsa, eski relay `X-Parasite-Party-Protocol`
göndermediği için 2.11'de skin paylaşımı çalışmaz ("the party server does not support
authenticated connections"). Bu kodu 2.11'den **önce** kurun. Lust ve Parasite ≤ 2.10 kurulumdan
sonra da eskisi gibi çalışır.

### Kurmadan önce kontrol (Durable Object riski)

Cloudflare, bir worker'daki Durable Object sınıflarını ve uygulanmış migration etiketlerini
(`wrangler.toml` içindeki `[[migrations]]`) hatırlar. Bu kodda:

- `ROOM` → sınıf `PartyRoom`, migration `v1` (`new_sqlite_classes = ["PartyRoom"]`)
- `DIRECTORY` → sınıf `FriendsDirectory`, migration `v2` (`new_sqlite_classes = ["FriendsDirectory"]`)

Lust'ın worker'ı da muhtemelen aynı adları kullanıyor (Parasite'in relay'i Lust'ınkinden geldi ve
Parasite ≤ 2.10 bugün `/friends`'i o relay'de kullanıyor), ama bunu görmeden emin olunamaz.
Cloudflare panelinde **Workers & Pages → lust-party-relay → Settings → Bindings** bölümüne bakın:

| Lust'ın worker'ında gördüğünüz | Ne olur |
|---|---|
| `ROOM: PartyRoom` ve `DIRECTORY: FriendsDirectory` | Sorun yok, doğrudan kurun. |
| Sadece `ROOM: PartyRoom` (DIRECTORY yok) | Kurulum `v2` migration'ını uygular, `FriendsDirectory` oluşur. Sorun yok. |
| Sınıf adı farklı (ör. `LustRoom`) | Cloudflare kurulumu **reddeder** (eski sınıf kodda yok). Eski worker çalışmaya devam eder. `wrangler.toml`'a bir `renamed_classes` migration'ı eklemek gerekir; bana sınıf adını ve migration etiketini söyleyin. |
| Migration etiketleri farklı (ör. `v1` yerine başka bir ad) | Wrangler eksik migration'ı uygulamaya çalışır; sınıf zaten varsa kurulum hata verir, eski worker çalışmaya devam eder. Etiketleri bana söyleyin, `wrangler.toml`'u ona göre düzenleyelim. |

Yani yanlış eşleşme çoğunlukla **kurulumun reddedilmesiyle** biter, çalışan relay bozulmaz. Oda ve
dizin verisi zaten geçicidir (odalar bağlantılarda yaşar, dizin 24 saatte silinir), bu yüzden
sınıf yeniden adlandırma veri kaybı açısından önemli değildir.

Migration etiketini görmek için (token ve hesap ID'siyle):

```bash
curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/workers/services/lust-party-relay" \
  | python -c "import json,sys; print(json.load(sys.stdin)['result']['default_environment']['script'].get('migration_tag'))"
```

`v2` görürseniz bu kodla aynı; `v1` görürseniz kurulum `v2`'yi ekler.

Diğer notlar:

- Kurulum, açık tüm WebSocket bağlantılarını keser; istemciler kendiliğinden yeniden bağlanır.
- Panelde worker'a elle eklenmiş değişken (Variables) varsa `--keep-vars` ile kurun (secret'lar
  her durumda kalır). Bu kod değişken kullanmaz.
- `wrangler.toml`'daki `name = "parasite-party-relay"`; Lust'ın worker'ına kurmak için her zaman
  `--name lust-party-relay` verin, yoksa ayrı, yeni bir worker oluşur.

### Yol A: kendi bilgisayarınızdan (wrangler login)

```bash
cd parasite/relay
npm ci
npx tsc --noEmit && npm test
npx wrangler login                                   # tarayıcıda Cloudflare hesabınızla giriş
npx wrangler versions list --name lust-party-relay   # geri dönüş için şu anki sürümün ID'sini not edin
npx wrangler deploy --name lust-party-relay --keep-vars
```

Doğrulama:

```bash
curl https://lust-party-relay.nysperado.workers.dev/
# {"status":"ok","service":"parasite-party-relay","protocols":[1,2]}  ← "protocols" görünüyorsa yeni kod
```

Repo kökünden tam kontrol (protokol 1, protokol 2, arkadaş dizini):

```bash
echo 'RELAY_URL = "wss://lust-party-relay.nysperado.workers.dev"' > party/network/relay_config.py
pip install websockets
python parasite/relay/check_rooms.py
```

Geri alma: `npx wrangler rollback --name lust-party-relay` (veya `versions list`'teki ID ile
`npx wrangler rollback <id> --name lust-party-relay`). Kurulum yeni bir migration uyguladıysa
(`v1` → `v2`) Cloudflare geri almayı reddedebilir; o zaman eski kodu yeniden kurmak gerekir.

### Yol B: GitHub Actions (`relay-deploy.yml`)

Workflow bugüne kadar secret'lar olmadığı için hep başarısız oldu. Çalışması için:

1. Cloudflare → **My Profile → API Tokens → Create Token → "Edit Cloudflare Workers"** şablonu.
   Hesap olarak relay'in olduğu hesabı seçin.
2. Hesap ID'si: Cloudflare panelinde **Workers & Pages** sayfasının sağında (Account ID).
3. GitHub → lustmyself/Parasite → **Settings → Secrets and variables → Actions**:
   - Secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
   - **Variables**: `PARASITE_RELAY_WORKER` = `lust-party-relay`
4. Çalıştırın: `gh workflow run "Deploy party relay" -R lustmyself/Parasite`
   (ayrıca `main`'e `parasite/relay/**` değişikliği girince kendiliğinden çalışır). Workflow önce
   `tsc` ve testleri çalıştırır, sonra kurar, sonra `check_rooms.py` ile kontrol eder.

`PARASITE_RELAY_WORKER` değişkenini **koymazsanız** workflow ayrı bir `parasite-party-relay`
worker'ı kurar ve sonraki build'ler (`write_config.py`) o adrese geçer: Parasite ve Lust
kullanıcıları ayrı relay'lerde kalır. Tek relay istiyorsanız değişkeni mutlaka koyun.
Secret'lar eklendikten sonra build'ler relay adresini hesabın `workers.dev` alt alan adından
bulur (`<worker>.<alt alan>.workers.dev`); bu, `nysperado` ise adres aynı kalır.
