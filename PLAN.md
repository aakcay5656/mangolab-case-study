# Uygulama Planı — Part A

Bu dosya sadece **kodun** planı. `NOTES.md` ve `REVIEW.md` bana ait değil;
onları sen dolduracaksın, bu plana dahil edilmediler.

Hedef süre: ~90 dakika. Ölçüt: "küçük ama dikkatli".

---

## 0. Sözleşme (değişmezler)

| Konu | Karar |
|---|---|
| Endpoint | `GET /tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28` |
| Upstream | `FX_UPSTREAM_BASE` env, default `https://api.frankfurter.dev`. Kodda **hiçbir yerde** gerçek host yazmayacak. |
| Port | `PORT` env, default `8080` |
| Scriptler | `./run.sh` servisi başlatır, `./test.sh` testleri çalıştırır (ağsız geçer) |

Parametre adları brief'te ne ise o: `amount`, `from`, `to`, `date`.
`from` Python'da anahtar kelime → `Query(alias="from")` ile karşılanacak.
(`tool.py`'deki `from_` / `on` isimleri sözleşmeyi bozuyor; biz bozmayacağız.)

## 0.1 Upstream'in ölçülmüş gerçek davranışı

Plan bunun üzerine kurulu, tahmin üzerine değil:

```
GET /v1/2026-08-29?base=EUR&symbols=TRY  → 200 {"date":"2026-08-28","rates":{"TRY":56.1718}}
GET /v1/2027-01-01  (gelecek)            → 404 {"message":"not found"}
GET /v1/1998-01-05  (seri öncesi)        → 404 {"message":"not found"}
GET /v1/latest?base=EUR&symbols=EUR      → {"message":"bad currency pair"}
GET /v1/latest?base=XXX&symbols=TRY      → 404
```

**En önemli tek cümle:** Upstream, hafta sonu/tatil için kendisi geriye doldurur
ve kullandığı gerçek tarihi `date` alanında söyler. Biz bu alanı **okuyacağız**,
asla kendimiz tarih üretmeyeceğiz.

## 0.2 Kritik karar — sorulan tarihte kur yoksa

**Cevap veriyoruz, ama gizlemiyoruz.** Upstream'in döndürdüğü `date` alanı
`rate_date` olur, kullanıcının sorduğu tarih `asked_date` olarak aynı cevapta durur.
İkisi farklıysa model bunu görür ve müşteriye "bu 28 Ağustos kuru" diyebilir.

- Uydurma yok: `rate` her zaman upstream'in o `date` için verdiği sayıdır.
- Yanlış etiket yok: bir kuru asla ait olmadığı tarihle sunmayız.
- `rate_date > asked_date` ise (gelecekten kur) **cevap vermeyiz**, hata döneriz.
- Bayat sınırı koymuyoruz (30 Aralık sorulup 24 Aralık kuru dönebilir); sınır
  yerine görünürlük tercih edildi, README'de yazacak.
- Gelecek tarih ve seri öncesi tarih: upstream'e gitmeden reddedilir.

## 0.3 Hata kodları (taslak)

| kod | HTTP | ne zaman |
|---|---|---|
| `invalid_amount` | 422 | eksik, 0, negatif, sayı değil, NaN/Inf, aşırı büyük |
| `invalid_currency` | 422 | biçim bozuk (3 harfli A–Z değil) |
| `unknown_currency` | 422 | biçim doğru ama ECB listesinde yok |
| `same_currency` | 400 | `from` == `to` (öneri: kur uydurmamak için reddet — sen istersen 1.0 dönerim) |
| `invalid_date` | 422 | tarih ayrıştırılamıyor |
| `date_in_future` | 422 | bugünden sonrası |
| `date_before_series` | 422 | 1999-01-04 öncesi |
| `no_rate_for_date` | 404 | upstream'de kullanılabilir kur yok |
| `upstream_timeout` | 504 | zaman aşımı |
| `upstream_unavailable` | 502 | bağlantı yok / DNS / 5xx |
| `upstream_invalid_response` | 502 | JSON değil, alan eksik, kur sayı değil |
| `internal_error` | 500 | son çare, gövdede detay yok |

Hata gövdesi her zaman: `{"error": "<kod>", "message": "<insanın okuyabileceği cümle>"}`

## 0.4 Dosya düzeni

```
fxtool/__init__.py
fxtool/main.py       FastAPI app, route, exception handler
fxtool/upstream.py   Frankfurter istemcisi + cache
fxtool/errors.py     hata kodları ve ToolError
fxtool/validate.py   amount / currency / date doğrulama
tests/               pytest, httpx MockTransport (ağ yok)
requirements.txt  run.sh  test.sh
```

---

## Adımlar

Her adımın sonunda dur, kodu incele, kendin commit'le.

### Adım 1 — Plan ve hata günlüğü
`PLAN.md` + `PITFALLS.md`. Kod yok.

```
docs: add implementation plan and pitfalls log
```

### Adım 2 — İskelet ve scriptler
`requirements.txt`, `fxtool/` paketi, `/health`, çalışan `run.sh` (uvicorn, `$PORT`,
`--reload` yok) ve `test.sh` (venv bootstrap + pytest). Tek bir smoke testi.
Bu adımın sonunda `./run.sh` gerçekten ayağa kalkar, `./test.sh` gerçekten yeşil yanar.

```
chore: scaffold fastapi service with working run.sh and test.sh
```

### Adım 3 — Hata sözleşmesi
`errors.py`: `ToolError(code, http_status, message)` + tek bir exception handler.
Doğrulama hataları dahil **her** hata aynı gövdeyi üretir (FastAPI'nin varsayılan
422 `detail` gövdesi de dönüştürülür). Testler: her kodun gövde şekli.

```
feat: add machine-readable error codes with a single error envelope
```

### Adım 4 — Girdi doğrulama (upstream'e dokunmadan)
`amount` `Decimal` olarak ayrıştırılır; 0/negatif/NaN/Inf/sayı-değil reddedilir,
ondalık basamak sayısı serbest ama sonuç 2 haneye yuvarlanır. Para bilerek
float ile çarpılmaz. Currency `^[A-Z]{3}$`, `date` ISO-8601, gelecek ve seri öncesi
burada reddedilir. Testler: her sınır durumu bir test.

```
feat: validate convert inputs before touching the upstream
```

### Adım 5 — Upstream istemcisi
`FX_UPSTREAM_BASE`'den okunan tek istemci, açık timeout (connect/read),
uygulama ömrü boyunca tek `AsyncClient` (lifespan ile kapatılır).
Cevap sertçe doğrulanır: HTTP durumu, `Content-Type`/JSON ayrıştırma, `date`
alanı var mı, `rates[to]` var mı ve sayı mı. Her arıza kendi hata koduna eşlenir.

```
feat: add frankfurter client with strict response validation and timeouts
```

### Adım 6 — Tarih dürüstlüğü
`rate_date` **yalnızca** payload'ın `date` alanından gelir. `rate_date > asked_date`
ise `upstream_invalid_response`. Sessiz `latest` fallback'i yok. Testler: hafta sonu
senaryosu (29 Ağustos sorulur, 28 Ağustos döner, ikisi de cevapta görünür).

```
feat: never present a rate under a date it does not belong to
```

### Adım 7 — Endpoint
`GET /tools/convert` uçtan uca bağlanır, brief'teki cevap şeması birebir
(`amount, from, to, rate, result, rate_date, asked_date, source`).
`rate` yuvarlanmaz, `result` 2 haneye yuvarlanır (ROUND_HALF_UP).

```
feat: implement GET /tools/convert
```

### Adım 8 — Cache
Anahtar `(from, to, istenen_tarih_parametresi)` — **tarih anahtarın parçası**.
Geçmiş tarihler değişmez → uzun TTL; `latest` → kısa TTL. Hatalar cache'lenmez.
Test: aynı soru iki kez sorulur, upstream'e **bir** istek gittiği doğrulanır;
farklı tarih sorulunca ikinci istek gittiği doğrulanır.

```
feat: cache upstream lookups per currency pair and date
```

### Adım 9 — Ağsız kanıt
Tüm testler `MockTransport` ile çalışır. Ek olarak: `FX_UPSTREAM_BASE` kapalı bir
porta bakarken servisin 502 `upstream_unavailable` döndüğünü kanıtlayan test.
`./test.sh` ağ tamamen kapalıyken geçer.

```
test: prove the service degrades safely with no upstream
```

### Adım 10 — README
Nasıl çalıştırılır, nasıl test edilir, hata kodları tablosu, brief'teki her
kenar durumda ne olduğu. Bir dakikada okunur.

```
docs: rewrite README with usage, error codes and edge-case behaviour
```

---

## Plana dahil değil

- `NOTES.md` — kararlar, bir gün daha olsa, AI kullanımı, AI'ın yanlış yaptığı şey.
- `REVIEW.md` — `tool.py` incelemesi, sıralı bulgular.

`PITFALLS.md` ikisi için de ham malzeme verir
