/**
 * Uçtan uca şifrelemenin kripto doğrulaması.
 *
 * static/js/e2ee.js içindeki gerçek fonksiyonları çalıştırır. Node 18+
 * WebCrypto'yu yerleşik sunduğu için tarayıcı açmadan doğrulanabiliyor.
 * (IndexedDB'ye dokunan fonksiyonlar burada çağrılmıyor.)
 *
 * Çalıştırmak için:
 *     node tests/e2ee-dogrula.mjs
 */

import {
  anahtarPaketiHazirla,
  b64Coz,
  grupAnahtariUret,
  grupAnahtariniCoz,
  grupAnahtariniSarmala,
  mesajCoz,
  mesajSifrele,
  parmakIziHesapla,
  PBKDF2_YINELEME,
} from "../static/js/e2ee.js";

let basarili = 0;
let basarisiz = 0;

function kontrol(ad, kosul) {
  if (kosul) {
    console.log(`  OK   ${ad}`);
    basarili++;
  } else {
    console.log(`  HATA ${ad}`);
    basarisiz++;
  }
}

async function hataBekle(ad, fn) {
  try {
    await fn();
    console.log(`  HATA ${ad} (hata bekleniyordu, olmadı)`);
    basarisiz++;
  } catch {
    console.log(`  OK   ${ad}`);
    basarili++;
  }
}

/** Tarayıcıdaki ozelAnahtariAc'ın IndexedDB'siz karşılığı. */
async function ozelAnahtariAcNode(kayit, parola) {
  const temel = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(parola),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  const kek = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: b64Coz(kayit.tuz), iterations: kayit.yineleme, hash: "SHA-256" },
    temel,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  const pkcs8 = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: b64Coz(kayit.iv) },
    kek,
    b64Coz(kayit.sifreli_ozel_anahtar),
  );
  return crypto.subtle.importKey(
    "pkcs8",
    pkcs8,
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["decrypt", "unwrapKey"],
  );
}

console.log("\n== Kimlik anahtarı ==");
const PAROLA = "cok-gizli-sifreleme-parolasi";
const { govde } = await anahtarPaketiHazirla(PAROLA);

kontrol("PBKDF2 yinelemesi 600.000", govde.yineleme === 600000 && PBKDF2_YINELEME === 600000);
kontrol("açık anahtar RSA-OAEP-256", govde.acik_anahtar.alg === "RSA-OAEP-256");
kontrol("açık anahtarda özel bileşen yok (d)", govde.acik_anahtar.d === undefined);
kontrol("açık anahtarda p/q yok", !govde.acik_anahtar.p && !govde.acik_anahtar.q);
kontrol("özel anahtar şifreli gönderiliyor", govde.sifreli_ozel_anahtar.length > 100);
kontrol("tuz 16 bayt", b64Coz(govde.tuz).length === 16);
kontrol("IV 12 bayt", b64Coz(govde.iv).length === 12);
kontrol("parmak izi üretildi", /^[0-9A-F ]{39}$/.test(govde.parmak_izi));
kontrol("parola pakette hiçbir yerde geçmiyor", !JSON.stringify(govde).includes(PAROLA));

console.log("\n== Parola ile açma ==");
const ozelAnahtar = await ozelAnahtariAcNode(govde, PAROLA);
kontrol("doğru parola özel anahtarı açtı", ozelAnahtar.type === "private");
kontrol("özel anahtar dışa aktarılamaz", ozelAnahtar.extractable === false);
await hataBekle("yanlış parola reddedildi", () => ozelAnahtariAcNode(govde, "yanlis-parola"));

console.log("\n== Grup anahtarı sarmalama ==");
const grupAnahtari = await grupAnahtariUret();
const sarmalanmis = await grupAnahtariniSarmala(grupAnahtari, govde.acik_anahtar);
kontrol("sarmalanmış anahtar base64", /^[A-Za-z0-9+/]+=*$/.test(sarmalanmis));

const acilanGrupAnahtari = await grupAnahtariniCoz(sarmalanmis, ozelAnahtar);
kontrol("grup anahtarı geri açıldı", acilanGrupAnahtari.algorithm.name === "AES-GCM");

const { govde: baskasi } = await anahtarPaketiHazirla("baska-parola-12345");
const baskasininOzeli = await ozelAnahtariAcNode(baskasi, "baska-parola-12345");
await hataBekle("başkasının anahtarıyla açılamıyor", () =>
  grupAnahtariniCoz(sarmalanmis, baskasininOzeli),
);

console.log("\n== Mesaj şifreleme ==");
const GRUP = "3f2b1a9c-0000-4444-8888-abcdefabcdef";
const SURUM = 1;
const GONDEREN = 42;
const DUZ_METIN = "Perşembe 21:00'de sahadayım, forma beyaz. ğüşıöç ✓";

const paket = await mesajSifrele(acilanGrupAnahtari, DUZ_METIN, GRUP, SURUM, GONDEREN);
kontrol("şifreli metin base64", /^[A-Za-z0-9+/]+=*$/.test(paket.sifreli_metin));
kontrol("IV 12 bayt", b64Coz(paket.iv).length === 12);
kontrol(
  "düz metin şifreli çıktıda görünmüyor",
  !Buffer.from(paket.sifreli_metin, "base64").toString("utf8").includes("sahadayım"),
);

const cozulen = await mesajCoz(
  acilanGrupAnahtari, paket.sifreli_metin, paket.iv, GRUP, SURUM, GONDEREN,
);
kontrol("mesaj doğru çözüldü (Türkçe karakterler dâhil)", cozulen === DUZ_METIN);

const paket2 = await mesajSifrele(acilanGrupAnahtari, DUZ_METIN, GRUP, SURUM, GONDEREN);
kontrol("aynı metin farklı şifreli çıktı üretiyor", paket2.sifreli_metin !== paket.sifreli_metin);

console.log("\n== AAD koruması (sunucu mesajla oynayamaz) ==");
await hataBekle("başka gruba taşınan mesaj çözülemiyor", () =>
  mesajCoz(acilanGrupAnahtari, paket.sifreli_metin, paket.iv,
    "00000000-0000-0000-0000-000000000000", SURUM, GONDEREN),
);
await hataBekle("gönderen değiştirilince çözülemiyor", () =>
  mesajCoz(acilanGrupAnahtari, paket.sifreli_metin, paket.iv, GRUP, SURUM, 999),
);
await hataBekle("anahtar sürümü değiştirilince çözülemiyor", () =>
  mesajCoz(acilanGrupAnahtari, paket.sifreli_metin, paket.iv, GRUP, 2, GONDEREN),
);

const bozuk = Buffer.from(paket.sifreli_metin, "base64");
bozuk[5] ^= 0xff;
await hataBekle("kurcalanmış şifreli metin reddediliyor", () =>
  mesajCoz(acilanGrupAnahtari, bozuk.toString("base64"), paket.iv, GRUP, SURUM, GONDEREN),
);

console.log("\n== Anahtar döndürme ==");
const yeniGrupAnahtari = await grupAnahtariUret();
await hataBekle("yeni sürüm anahtarı eski mesajı açamıyor", () =>
  mesajCoz(yeniGrupAnahtari, paket.sifreli_metin, paket.iv, GRUP, SURUM, GONDEREN),
);

console.log("\n== Parmak izi ==");
const pi1 = await parmakIziHesapla(govde.acik_anahtar);
const pi2 = await parmakIziHesapla(govde.acik_anahtar);
const pi3 = await parmakIziHesapla(baskasi.acik_anahtar);
kontrol("parmak izi kararlı", pi1 === pi2);
kontrol("farklı anahtar farklı parmak izi", pi1 !== pi3);

console.log("\n== Sabit parmak izi vektörü ==");
// Sunucu (apps/chat/services.py::parmak_izi_hesapla) aynı girdi için aynı
// değeri üretmek ZORUNDA. İkisi ayrı düşerse kullanıcı ekranda gördüğü
// parmak izini karşı tarafınkiyle karşılaştıramaz ve doğrulama fikri çöker.
// Python tarafı aynı vektörü apps/core/tests.py içinde sınıyor.
const SABIT_VEKTOR = { n: "sahte-modulus-degeri-123", e: "AQAB" };
const BEKLENEN = "C7F5 3AAD 10C3 328D E4D2 1AF8 4AEA 102B";
kontrol(
  "parmak izi sabit vektörü tutuyor (Python ile aynı)",
  (await parmakIziHesapla(SABIT_VEKTOR)) === BEKLENEN,
);
kontrol(
  "parmak izi biçimi: 8 öbek, dörder karakter",
  /^([0-9A-F]{4} ){7}[0-9A-F]{4}$/.test(pi1),
);

console.log(`\n${"=".repeat(46)}`);
console.log(`Başarılı: ${basarili}   Başarısız: ${basarisiz}`);
process.exit(basarisiz === 0 ? 0 : 1);
