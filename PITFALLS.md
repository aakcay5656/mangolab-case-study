# Hata Günlüğü — tekrarlamamak için

Amaç tek: **aynı hatayı iki kez yapmamak.** Buradaki her madde bir kural ve o
kuralı bizim yerimize hatırlayan bir test. Kural testte yaşamıyorsa, kural değildir.

Kayıt biçimi:

```
### H-xx — kısa ad
**Belirti:** dışarıdan nasıl görünür
**Müşteriye maliyeti:** para/güven cinsinden, linter cinsinden değil
**Kural:** bundan sonra ne yapıyoruz
**Yakalayan test:** test adı (yoksa "YOK — yazılacak")
```

> Not: aşağıdaki maddelerin bir kısmı `tool.py`'yi okurken görüldü. Burada
> **bizim kodumuz için kural** olarak duruyorlar. `REVIEW.md` senin işin ve
> oradaki cümleler senin olmalı; bu dosya onun yerine geçmez.

---

## Sessiz yanlış sayı (en pahalı sınıf)

### H-01 — cache anahtarında tarih yok
**Belirti:** 28 Ağustos sorulur, doğru cevap gelir; sonra 12 Mart sorulur, aynı
sayı döner. Hiçbir yerde hata yok.
**Müşteriye maliyeti:** yanlış tarihe ait kur, doğru kur gibi sunulur. Fatura
yanlış kesilir ve kimse fark etmez.
**Kural:** cache anahtarı `(from, to, tarih_parametresi)` üçlüsüdür. Tarihi
anahtardan düşüren bir değişiklik asla merge edilmez.
**Yakalayan test:** `test_cache_key_includes_date` — iki farklı tarih, iki upstream isteği.

### H-02 — `rate_date`'i biz hesaplamak
**Belirti:** cevaptaki `rate_date` her zaman sorulan tarih; upstream başka bir
tarihin kurunu döndürmüş olsa bile.
**Müşteriye maliyeti:** kur ait olmadığı güne etiketlenir. Brief'in yasakladığı
tam olarak bu.
**Kural:** `rate_date` yalnızca upstream payload'ının `date` alanından okunur.
`date.today()` veya sorulan tarih asla `rate_date` olamaz.
**Yakalayan test:** `test_the_rate_and_its_date_both_come_from_the_payload` — mock 28'i döner, biz 29'u sorduk, cevapta 28 yazar.

### H-03 — sessiz `latest` fallback'i
**Belirti:** geçmiş bir tarih için kur bulunamayınca sessizce bugünün kuruna düşmek.
**Müşteriye maliyeti:** aylar önceki bir işlem bugünün kuruyla hesaplanır; fark
sessizce müşterinin cebinden çıkar.
**Kural:** fallback varsa görünür olacak — `rate_date` ≠ `asked_date` cevapta
durur. Görünmeyen fallback yok.
**Yakalayan test:** `test_a_weekend_is_answered_with_the_previous_business_day_and_both_dates_show`

### H-04 — istisnayı yutup 200 dönmek
**Belirti:** upstream patlar, servis `rate: 0.0, result: 0.0` ile 200 döner.
**Müşteriye maliyeti:** modelin "bu bir hata" diyebileceği hiçbir sinyal yok;
müşteriye 0 TL denir. Yanlış sayı, sayı yokluğundan kötüdür.
**Kural:** başarısızlık her zaman non-2xx + `{"error", "message"}`. `except
Exception` sadece en dışta, ve orada da 500 üretir, 200 değil.
**Yakalayan test:** `test_an_upstream_failure_is_never_a_number` (uçtan uca hâli Adım 7'de)

### H-05 — gelecekten kur
**Belirti:** upstream sorulandan **sonraki** bir tarihin kurunu döndürür, biz kabul ederiz.
**Müşteriye maliyeti:** o gün henüz var olmayan bir kur, geçmiş bir işleme uygulanır.
**Kural:** `rate_date > asked_date` ise cevap vermeyiz, hata döneriz.
**Yakalayan test:** `test_a_rate_from_after_the_day_asked_about_is_refused`

## Sözleşme hataları

### H-06 — parametre adlarını değiştirmek
**Belirti:** brief `from`/`date` diyor, kod `from_`/`on` bekliyor. `from` Python'da
anahtar kelime olduğu için "çözüm" gibi görünüyor.
**Müşteriye maliyeti:** çağıran her istemci 422 alır. Servis çalışıyor ama kimse kullanamıyor.
**Kural:** dış isim brief'teki isimdir; Python tarafındaki sorun `Query(alias="from")`
ile çözülür, sözleşme değiştirilerek değil.
**Yakalayan test:** `test_accepts_exact_query_contract_from_brief`

### H-07 — upstream host'unu koda gömmek
**Belirti:** `UPSTREAM = "https://api.frankfurter.dev/v1"` sabiti.
**Müşteriye maliyeti:** doğrudan değil — ama sahte upstream ile inceleme yapılamaz,
test ağa bağımlı hale gelir ve H-01..H-05 sınıfı hatalar test edilemez olur.
**Kural:** gerçek host yalnızca `FX_UPSTREAM_BASE`'in default'unda geçer, başka
hiçbir yerde. `grep -rn "frankfurter" fxtool/` tek bir satır göstermeli.
**Yakalayan test:** `test_the_real_host_appears_only_as_a_default` (kaynak dosyaları tarar)

## Para ve sayı

### H-08 — kuru yuvarlamak
**Belirti:** `rate = round(rate, 2)`.
**Müşteriye maliyeti:** 56.1718 → 56.17; 250 EUR'da ~45 kuruş, 1.000.000 EUR'da
1.800 TL sapma. Cevap "doğru görünür".
**Kural:** `rate` upstream'den geldiği gibi durur. Yalnızca `result` yuvarlanır.
**Yakalayan test:** `test_rate_is_not_rounded`

### H-09 — para float ile
**Belirti:** `amount * rate` float aritmetiği, `round()` banker yuvarlaması.
**Müşteriye maliyeti:** kuruş sapmaları ve mutabakat tutmayan raporlar.
**Kural:** `Decimal` + `ROUND_HALF_UP`, çıktıya çevrilirken tek noktada dönüşüm.
**Yakalayan test:** `test_half_up_rounding`

### H-10 — `amount`'ı doğrulamamak
**Belirti:** 0, negatif, `NaN`, `1e400` kabul edilir.
**Müşteriye maliyeti:** anlamsız veya `NaN` sonuç modele "sayı" diye gider.
**Kural:** upstream'e gitmeden önce `amount > 0` ve sonlu olacak.
**Yakalayan test:** `test_amounts_that_cannot_mean_money_are_refused` (parametrize)

## Dayanıklılık

### H-11 — timeout'suz HTTP istemcisi
**Belirti:** `httpx.AsyncClient()` çıplak — varsayılan davranışa güvenmek.
**Müşteriye maliyeti:** yavaş upstream tüm worker'ları tutar; servis çalışıyor
görünürken hiçbir isteğe cevap vermez.
**Kural:** connect ve read timeout'ları açıkça yazılır; timeout `504` üretir.
**Yakalayan test:** `test_a_slow_upstream_times_out_instead_of_hanging`

### H-12 — `response.json()` körlemesine
**Belirti:** upstream HTML hata sayfası döner, `json()` patlar veya sözlük beklenmedik şekilde gelir.
**Müşteriye maliyeti:** 500 veya H-04'teki gibi sahte 0.
**Kural:** durum kodu → JSON ayrıştırma → alan varlığı → tip kontrolü, bu sırayla
ve her biri kendi hata koduyla.
**Yakalayan test:** `test_html_instead_of_json_is_an_error_not_a_crash`

### H-13 — ağa muhtaç testler
**Belirti:** testler yerelde geçer, kapalı portla çalıştırılınca patlar.
**Müşteriye maliyeti:** dolaylı — yukarıdaki hataların hiçbiri yakalanamaz.
**Kural:** varsayılan test yolu `MockTransport`; ayrıca kapalı porta bakan
tek bir gerçek-soket testi 502'yi kanıtlar. `./test.sh` ağsız yeşil yanar.
**Yakalayan test:** tüm suite + `test_closed_port_returns_502`

### H-14 — `run.sh` prod gibi davranmamak
**Belirti:** `--reload`, sabit port, `$PORT` yok sayılır.
**Müşteriye maliyeti:** inceleyen kişi servisi beklediği portta bulamaz.
**Kural:** `uvicorn --host 0.0.0.0 --port "${PORT:-8080}"`, reload yok.
**Yakalayan test:** YOK — el ile: `PORT=9099 ./run.sh` ve `curl :9099/health`.

---

## Süreç kuralları

- **S-01 — Upstream davranışını tahmin etme, ölç.** Hafta sonu geri-doldurma,
  gelecek tarih ve bilinmeyen kur davranışı `curl` ile doğrulandı; plan bunun
  üzerine kuruldu. Yeni bir varsayım çıkarsa önce ölç.
- **S-02 — Yeni bir hata bulunduğunda önce buraya yaz, sonra düzelt.** Sıra
  tersine dönerse kural kaybolur, sadece yama kalır.
- **S-03 — Her madde bir teste bağlanır.** "Yakalayan test: YOK" satırı açık bir borçtur.
