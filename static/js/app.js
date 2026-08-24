/**
 * Genel arayüz davranışları.
 *
 * Not: CSP satır içi stil özniteliğini (style="…") engelliyor. Bu yüzden
 * yüzde değerleri şablonda data-yuzde ile taşınıp burada CSSOM üzerinden
 * yazılıyor — bu yol CSP tarafından kısıtlanmıyor.
 */

document.addEventListener("DOMContentLoaded", () => {
  yuzdeleriUygula();
  onaylariBagla();
  kopyalamayiBagla();
  yenilemeyiBagla();
  buyutecBagla();
  servisCalisaniniKaydet();
  sifrelemeDeposunuDenetle();
});

/**
 * Şifreleme deposunun sahibini her sayfa açılışında denetler.
 *
 * Çözülmüş sohbet anahtarları IndexedDB içinde kalıcı duruyor ve çıkış
 * yapmak onları silmiyordu. Tek temizleme yolu sohbet sayfasındaki "Bu
 * tarayıcıda kilitle" düğmesiydi; çıkış yapan birinin ona basmak için
 * hiçbir sebebi yok. Paylaşılan bir telefonda bu, çıkmış bir kullanıcının
 * açılmış RSA özel anahtarının ve grup AES anahtarlarının cihazda kalması
 * demekti.
 *
 * Tek kural var: depodaki anahtarlar o an giriş yapmış kişiye ait değilse
 * depo silinir. Çıkış, hesap değiştirme ve oturumun düşmesi aynı yoldan
 * temizleniyor.
 *
 * Kimliğin BİLİNMEDİĞİ sayfalarda hiçbir şey yapılmıyor: ağın gitmesi
 * anahtarların silinmesi için sebep değil.
 *
 * Depo sabitleri e2ee.js ile aynı olmak ZORUNDA; apps/core/tests.py ikisini
 * karşılaştırıyor. Buraya kopyalanmalarının sebebi, app.js her sayfada
 * yükleniyor olması: yalnızca bu denetim için sohbet modülünü de her sayfaya
 * çektirmek gereksiz bir istek demekti.
 */
const E2EE_DB_ADI = "halisaha-e2ee";
const E2EE_DEPO_ADI = "anahtarlar";
const E2EE_SAHIP_ANAHTARI = "sahip";
const E2EE_DB_SURUM = 1;

function sifrelemeDeposunuDenetle() {
  const govde = document.body;
  if (!govde || !window.indexedDB) return;

  const ham = govde.dataset.kullaniciId;
  let kimlik;
  if (ham) kimlik = String(ham);
  else if (govde.dataset.oturum === "kapali") kimlik = null;
  else return; // kimlik bilinmiyor (örn. cihazdan açılan çevrimdışı sayfası)

  let istek;
  try {
    // Sürüm ve onupgradeneeded, e2ee.js ile BİREBİR aynı olmak zorunda.
    // Sürümsüz açılsaydı veritabanı sürüm 1 olarak ama nesne deposu
    // olmadan yaratılırdı; e2ee.js sonra sürüm 1'i açtığında yükseltme
    // tetiklenmez, depo hiç oluşmaz ve sohbet açılmaz olurdu.
    istek = indexedDB.open(E2EE_DB_ADI, E2EE_DB_SURUM);
  } catch {
    return; // gizli sekme ya da depolama izni yok
  }

  istek.onupgradeneeded = () => {
    const db = istek.result;
    if (!db.objectStoreNames.contains(E2EE_DEPO_ADI)) {
      db.createObjectStore(E2EE_DEPO_ADI);
    }
  };
  istek.onerror = () => {};
  istek.onsuccess = () => {
    const db = istek.result;
    if (!db.objectStoreNames.contains(E2EE_DEPO_ADI)) {
      db.close();
      return;
    }
    let okuma;
    try {
      okuma = db.transaction(E2EE_DEPO_ADI, "readonly")
        .objectStore(E2EE_DEPO_ADI)
        .get(E2EE_SAHIP_ANAHTARI);
    } catch {
      db.close();
      return;
    }
    okuma.onerror = () => db.close();
    okuma.onsuccess = () => {
      const mevcut = okuma.result ?? null;
      if (mevcut === kimlik) {
        db.close();
        return;
      }
      try {
        const islem = db.transaction(E2EE_DEPO_ADI, "readwrite");
        const depo = islem.objectStore(E2EE_DEPO_ADI);
        depo.clear();
        if (kimlik !== null) depo.put(kimlik, E2EE_SAHIP_ANAHTARI);
        islem.oncomplete = () => db.close();
        islem.onerror = () => db.close();
      } catch {
        db.close();
      }
    };
  };
}

function yuzdeleriUygula() {
  document.querySelectorAll("[data-yuzde]").forEach((el) => {
    const ham = Number(el.dataset.yuzde);
    if (Number.isFinite(ham)) {
      el.style.setProperty("--yuzde", Math.max(0, Math.min(100, ham)));
    }
  });
}

/** Yıkıcı işlemler için onay — data-onay özniteliğindeki metinle sorar. */
function onaylariBagla() {
  document.querySelectorAll("form[data-onay]").forEach((form) => {
    form.addEventListener("submit", (olay) => {
      if (!window.confirm(form.dataset.onay)) olay.preventDefault();
    });
  });
}

/**
 * Fotoğraf büyüteci.
 *
 * [data-buyutec] taşıyan bir düğmeye tıklanınca fotoğrafın büyük hâli
 * ekranı kaplayan bir katmanda açılır. <dialog> kullanılıyor: odak tuzağı,
 * Esc ile kapanma ve arka planın erişilemez olması tarayıcıdan geliyor,
 * bunları elle yazmaya gerek kalmıyor.
 */
function buyutecBagla() {
  const tetikleyiciler = document.querySelectorAll("[data-buyutec]");
  if (!tetikleyiciler.length) return;

  const katman = document.getElementById("buyutec");
  if (!katman) return;

  const gorsel = katman.querySelector("[data-buyutec-gorsel]");
  const baslik = katman.querySelector("[data-buyutec-baslik]");
  const kapat = katman.querySelector("[data-buyutec-kapat]");
  const indir = katman.querySelector("[data-buyutec-indir]");

  tetikleyiciler.forEach((tetik) => {
    tetik.addEventListener("click", () => {
      gorsel.src = tetik.dataset.buyutec;
      gorsel.alt = tetik.dataset.buyutecAlt || "";
      if (baslik) baslik.textContent = tetik.dataset.buyutecBaslik || "";

      // İndirme bağlantısı yalnızca fotoğrafta indirme adresi varsa görünür.
      // Profil fotoğraflarında yok: başkasının fotoğrafına indirme düğmesi
      // koymak istemedik.
      if (indir) {
        const adres = tetik.dataset.buyutecIndir;
        if (adres) {
          indir.href = adres;
          indir.hidden = false;
        } else {
          indir.removeAttribute("href");
          indir.hidden = true;
        }
      }

      katman.showModal();
    });
  });

  if (kapat) kapat.addEventListener("click", () => katman.close());

  // Fotoğrafın dışına tıklayınca kapansın. <dialog> tıklamayı kendi
  // kutusunda topladığı için hedefin katmanın kendisi olması yeterli.
  katman.addEventListener("click", (olay) => {
    if (olay.target === katman) katman.close();
  });

  // Kapanınca kaynağı boşalt: arka planda gereksiz yere bellekte durmasın.
  katman.addEventListener("close", () => {
    gorsel.removeAttribute("src");
  });
}

/** Davet bağlantısını panoya kopyalama. */
function kopyalamayiBagla() {
  document.querySelectorAll("[data-kopyala]").forEach((dugme) => {
    dugme.addEventListener("click", async () => {
      const kaynak = document.querySelector(dugme.dataset.kopyala);
      if (!kaynak) return;
      const metin = kaynak.textContent.trim();
      const eskiYazi = dugme.textContent;
      try {
        await navigator.clipboard.writeText(metin);
        dugme.textContent = "Kopyalandı";
      } catch {
        // Pano izni yoksa metni seçili hâle getir, kullanıcı elle kopyalasın.
        const secim = window.getSelection();
        const aralik = document.createRange();
        aralik.selectNodeContents(kaynak);
        secim.removeAllRanges();
        secim.addRange(aralik);
        dugme.textContent = "Kopyalamak için Ctrl+C";
      }
      setTimeout(() => {
        dugme.textContent = eskiYazi;
      }, 2200);
    });
  });
}
