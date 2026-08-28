/**
 * Sıradaki maçı bu cihazda saklama.
 *
 * NEDEN VAR: sahanın önünde, çekmeyen bir telefonda insanın istediği tek
 * ekran "saat kaçta, nerede, kim geliyor" ekranı. Servis çalışanı tasarım
 * gereği hiçbir kişisel şeyi diske yazmıyordu (telefon elden ele geziyor),
 * dolayısıyla tam da o ekran çevrimdışıyken ulaşılamaz olan ekrandı.
 *
 * Yasağı kaldırmak yerine daraltıyoruz: kullanıcı açıkça açıyor ve yalnızca
 * SIRADAKİ maçın özeti kalıyor. Puan yok, sohbet yok, geçmiş yok, fotoğraf
 * yok (bkz. apps/matches/views.py::sonraki_mac_ozeti).
 *
 * Silinme yolu hazırdı: depo sahibi denetimi (static/js/app.js) giriş yapan
 * kişi değişince bu deponun tamamını siliyor. Yani çıkış yapmak, hesap
 * değiştirmek ve sohbeti kilitlemek bu kaydı da götürüyor.
 *
 * Bu dosya iki yerde çalışıyor:
 *   · panelde  — açma/kapama anahtarı ve tazeleme
 *   · çevrimdışı sayfasında — saklanan özeti gösterme
 * İkisi tek dosyada çünkü servis çalışanı bunu ön belleğe alıyor; iki ayrı
 * dosya iki ayrı ön yükleme demekti.
 *
 * İÇE AKTARMA YOK: çevrimdışı sayfası bunu ön bellekten çalıştırıyor ve
 * üretimde statik dosya adları karma taşıdığı için göreli bir import
 * çevrimdışıyken çözülemiyor (bkz. apps/core/tests.py).
 */

const DB_ADI = "halisaha-e2ee";
const DEPO_ADI = "anahtarlar";
const DB_SURUM = 1;
const ACIK_ANAHTARI = "cevrimdisi:acik";
const MAC_ANAHTARI = "cevrimdisi:mac";

/* --- Küçük IndexedDB yardımcıları ------------------------------------- */
function dbAc() {
  return new Promise((coz, hata) => {
    let istek;
    try {
      istek = indexedDB.open(DB_ADI, DB_SURUM);
    } catch (e) {
      hata(e);
      return;
    }
    istek.onupgradeneeded = () => {
      const db = istek.result;
      if (!db.objectStoreNames.contains(DEPO_ADI)) db.createObjectStore(DEPO_ADI);
    };
    istek.onsuccess = () => coz(istek.result);
    istek.onerror = () => hata(istek.error);
  });
}

async function oku(anahtar) {
  const db = await dbAc();
  try {
    if (!db.objectStoreNames.contains(DEPO_ADI)) return null;
    return await new Promise((coz, hata) => {
      const istek = db.transaction(DEPO_ADI, "readonly").objectStore(DEPO_ADI).get(anahtar);
      istek.onsuccess = () => coz(istek.result ?? null);
      istek.onerror = () => hata(istek.error);
    });
  } finally {
    db.close();
  }
}

async function yaz(anahtar, deger) {
  const db = await dbAc();
  try {
    await new Promise((coz, hata) => {
      const islem = db.transaction(DEPO_ADI, "readwrite");
      if (deger === null) islem.objectStore(DEPO_ADI).delete(anahtar);
      else islem.objectStore(DEPO_ADI).put(deger, anahtar);
      islem.oncomplete = () => coz();
      islem.onerror = () => hata(islem.error);
    });
  } finally {
    db.close();
  }
}

/* --- Panel: açma/kapama ------------------------------------------------- */
async function macOzetiniTazele() {
  const yanit = await fetch("/maclar/sonraki/", {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!yanit.ok) throw new Error("Maç bilgisi alınamadı.");
  const veri = await yanit.json();
  await yaz(MAC_ANAHTARI, veri.mac ? veri : null);
  return veri.mac;
}

async function anahtariBagla(kutu) {
  const durum = kutu.parentElement.querySelector("[data-cevrimdisi-durum]");
  const yaz_durum = (metin) => {
    if (durum) durum.textContent = metin;
  };

  if (!window.indexedDB) {
    kutu.disabled = true;
    yaz_durum("Bu tarayıcı cihazda saklamayı desteklemiyor.");
    return;
  }

  try {
    kutu.checked = (await oku(ACIK_ANAHTARI)) === true;
  } catch {
    kutu.disabled = true;
    yaz_durum("Cihaz deposuna erişilemiyor.");
    return;
  }

  if (kutu.checked) {
    // Açıksa her panel ziyaretinde sessizce tazele: kadro değişmiş olabilir.
    macOzetiniTazele().catch(() => {});
    yaz_durum("Sıradaki maç bu cihazda saklanıyor.");
  }

  kutu.addEventListener("change", async () => {
    kutu.disabled = true;
    try {
      if (kutu.checked) {
        await yaz(ACIK_ANAHTARI, true);
        const mac = await macOzetiniTazele();
        yaz_durum(
          mac
            ? "Kaydedildi. Bağlantın yokken de görebilirsin."
            : "Açıldı. Sıradaki maç eklendiğinde kaydedilecek.",
        );
      } else {
        await yaz(ACIK_ANAHTARI, null);
        await yaz(MAC_ANAHTARI, null);
        yaz_durum("Kapatıldı ve cihazdaki kopya silindi.");
      }
    } catch {
      kutu.checked = !kutu.checked;
      yaz_durum("İşlem tamamlanamadı.");
    } finally {
      kutu.disabled = false;
    }
  });
}

/* --- Çevrimdışı sayfası: saklananı göster ------------------------------- */
function satir(etiket, deger) {
  const p = document.createElement("p");
  const b = document.createElement("strong");
  b.textContent = etiket + " ";
  p.append(b, document.createTextNode(deger));
  return p;
}

function isimListesi(baslik, isimler) {
  const bolum = document.createElement("div");
  const h = document.createElement("h3");
  h.textContent = baslik;
  const ul = document.createElement("ul");
  ul.className = "cevrimdisi-kadro";
  for (const ad of isimler) {
    const li = document.createElement("li");
    li.textContent = ad; // textContent: ad hiçbir zaman HTML olarak yorumlanmaz
    ul.append(li);
  }
  bolum.append(h, ul);
  return bolum;
}

async function saklananiGoster(kap) {
  let kayit = null;
  try {
    kayit = await oku(MAC_ANAHTARI);
  } catch {
    return; // depo yok ya da kapalı; bölüm gizli kalsın
  }
  if (!kayit || !kayit.mac) return;

  const mac = kayit.mac;
  kap.replaceChildren();

  const baslik = document.createElement("h2");
  baslik.textContent = "Sıradaki maç";
  kap.append(baslik);

  const grup = document.createElement("p");
  grup.className = "uststart";
  grup.textContent = mac.grup;
  kap.append(grup);

  kap.append(satir("Tarih:", `${mac.gun} · ${mac.saat}`));
  if (mac.konum) kap.append(satir("Saha:", mac.konum));
  kap.append(satir("Süre:", `${mac.sure_dakika} dakika`));

  if (mac.takimlar && mac.takimlar.length) {
    for (const takim of mac.takimlar) {
      if (takim.oyuncular.length) kap.append(isimListesi(takim.ad, takim.oyuncular));
    }
  } else if (mac.gelenler && mac.gelenler.length) {
    kap.append(isimListesi("Geliyorum diyenler", mac.gelenler));
  }

  if (kayit.guncellendi) {
    const not = document.createElement("p");
    not.className = "kucuk solgun";
    const t = new Date(kayit.guncellendi);
    not.textContent =
      "Bu bilgi " +
      t.toLocaleString("tr-TR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }) +
      " itibarıyla kaydedildi; o günden sonra değişmiş olabilir.";
    kap.append(not);
  }

  kap.hidden = false;
}

/* --- Bağlama ------------------------------------------------------------ */
const anahtar = document.querySelector("[data-cevrimdisi-anahtari]");
if (anahtar) anahtariBagla(anahtar).catch(() => {});

const kap = document.getElementById("cevrimdisi-mac");
if (kap) saklananiGoster(kap).catch(() => {});
