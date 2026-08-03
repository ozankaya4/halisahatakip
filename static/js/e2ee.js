/**
 * Uçtan uca şifreleme — tarayıcı tarafı.
 *
 * Sunucu bu dosyadaki hiçbir sırrı görmez. Buradaki kural basittir:
 * düz metin ve anahtar materyali asla ağa çıkmaz.
 *
 * Kullanılan algoritmalar (hepsi WebCrypto yerleşiği, harici kütüphane yok):
 *   · Kimlik anahtarı   : RSA-OAEP 2048 bit, SHA-256
 *   · Parola türetme    : PBKDF2-SHA256, 600.000 yineleme, 16 bayt tuz
 *   · Grup anahtarı     : AES-GCM 256 bit
 *   · Mesaj             : AES-GCM, mesaj başına rastgele 12 baytlık IV
 *
 * Mesaj şifrelemesinde ek doğrulanmış veri (AAD) olarak
 * "grupId:anahtarSürümü:gönderenId" kullanılır. Böylece sunucu bir mesajı
 * başka bir gruba taşıyamaz ya da göndereni değiştiremez — bu alanlarla
 * oynanırsa çözme başarısız olur.
 */

export const PBKDF2_YINELEME = 600000;
const TUZ_UZUNLUK = 16;
const IV_UZUNLUK = 12;

const DB_ADI = "halisaha-e2ee";
const DEPO_ADI = "anahtarlar";
const DB_SURUM = 1;

const metinKodlayici = new TextEncoder();
const metinCozucu = new TextDecoder();

/* -------------------------------------------------------------------------
 * base64 yardımcıları
 * ---------------------------------------------------------------------- */
export function b64Kodla(tampon) {
  const baytlar = new Uint8Array(tampon);
  let ikili = "";
  const parca = 0x8000;
  for (let i = 0; i < baytlar.length; i += parca) {
    ikili += String.fromCharCode.apply(null, baytlar.subarray(i, i + parca));
  }
  return btoa(ikili);
}

export function b64Coz(metin) {
  const ikili = atob(metin);
  const baytlar = new Uint8Array(ikili.length);
  for (let i = 0; i < ikili.length; i++) baytlar[i] = ikili.charCodeAt(i);
  return baytlar;
}

function rastgele(uzunluk) {
  return crypto.getRandomValues(new Uint8Array(uzunluk));
}

/* -------------------------------------------------------------------------
 * IndexedDB — çözülmüş anahtarların oturum deposu
 *
 * Özel anahtar buraya extractable:false olarak yazılır: JavaScript onu
 * kullanabilir ama ham baytlarını okuyamaz. Böylece olası bir XSS'te bile
 * anahtar dışarı sızdırılamaz (mevcut oturumda kötüye kullanılabilir, ama
 * kalıcı olarak çalınamaz). CSP'nin sıkı tutulmasının nedeni budur.
 * ---------------------------------------------------------------------- */
function dbAc() {
  return new Promise((coz, hata) => {
    const istek = indexedDB.open(DB_ADI, DB_SURUM);
    istek.onupgradeneeded = () => {
      const db = istek.result;
      if (!db.objectStoreNames.contains(DEPO_ADI)) db.createObjectStore(DEPO_ADI);
    };
    istek.onsuccess = () => coz(istek.result);
    istek.onerror = () => hata(istek.error);
  });
}

async function depoyaYaz(anahtar, deger) {
  const db = await dbAc();
  return new Promise((coz, hata) => {
    const islem = db.transaction(DEPO_ADI, "readwrite");
    islem.objectStore(DEPO_ADI).put(deger, anahtar);
    islem.oncomplete = () => { db.close(); coz(); };
    islem.onerror = () => { db.close(); hata(islem.error); };
  });
}

async function depodanOku(anahtar) {
  const db = await dbAc();
  return new Promise((coz, hata) => {
    const islem = db.transaction(DEPO_ADI, "readonly");
    const istek = islem.objectStore(DEPO_ADI).get(anahtar);
    istek.onsuccess = () => { db.close(); coz(istek.result ?? null); };
    istek.onerror = () => { db.close(); hata(istek.error); };
  });
}

export async function depoyuTemizle() {
  const db = await dbAc();
  return new Promise((coz, hata) => {
    const islem = db.transaction(DEPO_ADI, "readwrite");
    islem.objectStore(DEPO_ADI).clear();
    islem.oncomplete = () => { db.close(); coz(); };
    islem.onerror = () => { db.close(); hata(islem.error); };
  });
}

const ozelAnahtarAdi = (kullaniciId) => `ozel:${kullaniciId}`;
const grupAnahtarAdi = (grupId, surum) => `grup:${grupId}:${surum}`;

export async function ozelAnahtariAl(kullaniciId) {
  return depodanOku(ozelAnahtarAdi(kullaniciId));
}

export async function grupAnahtariniAl(grupId, surum) {
  return depodanOku(grupAnahtarAdi(grupId, surum));
}

export async function grupAnahtariniSakla(grupId, surum, anahtar) {
  return depoyaYaz(grupAnahtarAdi(grupId, surum), anahtar);
}

/* -------------------------------------------------------------------------
 * Kimlik anahtarı
 * ---------------------------------------------------------------------- */
export async function anahtarCiftiUret() {
  return crypto.subtle.generateKey(
    {
      name: "RSA-OAEP",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["encrypt", "decrypt", "wrapKey", "unwrapKey"],
  );
}

async function parolaAnahtariTuret(parola, tuz, yineleme) {
  const temel = await crypto.subtle.importKey(
    "raw",
    metinKodlayici.encode(parola),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: tuz, iterations: yineleme, hash: "SHA-256" },
    temel,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

/** Açık anahtarın okunabilir parmak izi — kullanıcılar birbirini doğrulayabilsin. */
export async function parmakIziHesapla(acikJwk) {
  const veri = metinKodlayici.encode(`${acikJwk.n}.${acikJwk.e}`);
  const ozet = await crypto.subtle.digest("SHA-256", veri);
  const onalti = Array.from(new Uint8Array(ozet))
    .slice(0, 16)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return (onalti.match(/.{4}/g) || []).join(" ").toUpperCase();
}

/**
 * Yeni anahtar çifti üretir ve sunucuya gönderilecek paketi hazırlar.
 * Parola bu fonksiyondan dışarı çıkmaz.
 */
export async function anahtarPaketiHazirla(parola) {
  const cift = await anahtarCiftiUret();
  const acikJwk = await crypto.subtle.exportKey("jwk", cift.publicKey);
  const pkcs8 = await crypto.subtle.exportKey("pkcs8", cift.privateKey);

  const tuz = rastgele(TUZ_UZUNLUK);
  const iv = rastgele(IV_UZUNLUK);
  const kek = await parolaAnahtariTuret(parola, tuz, PBKDF2_YINELEME);
  const sifreli = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, kek, pkcs8);

  // JWK'yı sadeleştir: sunucuya yalnızca gereken alanlar gitsin.
  const temizJwk = {
    kty: acikJwk.kty,
    n: acikJwk.n,
    e: acikJwk.e,
    alg: "RSA-OAEP-256",
    ext: true,
  };

  return {
    govde: {
      acik_anahtar: temizJwk,
      sifreli_ozel_anahtar: b64Kodla(sifreli),
      tuz: b64Kodla(tuz),
      iv: b64Kodla(iv),
      yineleme: PBKDF2_YINELEME,
      parmak_izi: await parmakIziHesapla(temizJwk),
    },
  };
}

/**
 * Sunucudan gelen şifreli özel anahtarı parolayla çözer ve oturuma yükler.
 * Parola yanlışsa AES-GCM doğrulaması başarısız olur ve hata fırlatılır.
 */
export async function ozelAnahtariAc(kullaniciId, kayit, parola) {
  const kek = await parolaAnahtariTuret(
    parola,
    b64Coz(kayit.tuz),
    kayit.yineleme,
  );

  let pkcs8;
  try {
    pkcs8 = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: b64Coz(kayit.iv) },
      kek,
      b64Coz(kayit.sifreli_ozel_anahtar),
    );
  } catch {
    throw new Error("Şifreleme parolası yanlış.");
  }

  // extractable:false → anahtar bir daha dışa aktarılamaz.
  const ozelAnahtar = await crypto.subtle.importKey(
    "pkcs8",
    pkcs8,
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["decrypt", "unwrapKey"],
  );

  await depoyaYaz(ozelAnahtarAdi(kullaniciId), ozelAnahtar);
  return ozelAnahtar;
}

/* -------------------------------------------------------------------------
 * Grup anahtarı
 * ---------------------------------------------------------------------- */
export async function grupAnahtariUret() {
  // extractable:true olmak zorunda: yeni üyeler için sarmalayabilmemiz gerekiyor.
  return crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, [
    "encrypt",
    "decrypt",
  ]);
}

async function acikAnahtariIceriAl(jwk) {
  return crypto.subtle.importKey(
    "jwk",
    { ...jwk, alg: "RSA-OAEP-256", ext: true },
    { name: "RSA-OAEP", hash: "SHA-256" },
    true,
    ["encrypt", "wrapKey"],
  );
}

/** Grup anahtarını tek bir üyenin açık anahtarıyla sarmalar. */
export async function grupAnahtariniSarmala(grupAnahtari, acikJwk) {
  const acik = await acikAnahtariIceriAl(acikJwk);
  const sarmalanmis = await crypto.subtle.wrapKey("raw", grupAnahtari, acik, {
    name: "RSA-OAEP",
  });
  return b64Kodla(sarmalanmis);
}

/** Sunucudan gelen sarmalanmış grup anahtarını kendi özel anahtarımızla açar. */
export async function grupAnahtariniCoz(sarmalanmisB64, ozelAnahtar) {
  return crypto.subtle.unwrapKey(
    "raw",
    b64Coz(sarmalanmisB64),
    ozelAnahtar,
    { name: "RSA-OAEP" },
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"],
  );
}

/* -------------------------------------------------------------------------
 * Mesaj
 * ---------------------------------------------------------------------- */
function aadUret(grupId, surum, gonderenId) {
  return metinKodlayici.encode(`${grupId}:${surum}:${gonderenId}`);
}

export async function mesajSifrele(grupAnahtari, metin, grupId, surum, gonderenId) {
  const iv = rastgele(IV_UZUNLUK);
  const sifreli = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: aadUret(grupId, surum, gonderenId),
    },
    grupAnahtari,
    metinKodlayici.encode(metin),
  );
  return { sifreli_metin: b64Kodla(sifreli), iv: b64Kodla(iv) };
}

export async function mesajCoz(grupAnahtari, sifreliB64, ivB64, grupId, surum, gonderenId) {
  const duz = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: b64Coz(ivB64),
      additionalData: aadUret(grupId, surum, gonderenId),
    },
    grupAnahtari,
    b64Coz(sifreliB64),
  );
  return metinCozucu.decode(duz);
}

/* -------------------------------------------------------------------------
 * Ortam kontrolü
 * ---------------------------------------------------------------------- */
export function webcryptoVarMi() {
  // crypto.subtle yalnızca güvenli bağlamlarda (HTTPS ya da localhost) vardır.
  return typeof crypto !== "undefined" && !!crypto.subtle && !!window.indexedDB;
}
