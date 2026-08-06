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
});

/** Çevrimdışı sayfasındaki "Yeniden dene" düğmesi. */
function yenilemeyiBagla() {
  document.querySelectorAll("[data-yenile]").forEach((dugme) => {
    dugme.addEventListener("click", () => window.location.reload());
  });
}

/**
 * Ana ekrana eklenebilmesi için servis çalışanını kaydeder.
 *
 * Kök yoldan (/sw.js) kaydediliyor: bir servis çalışanı yalnızca bulunduğu
 * klasör ve altını yönetebilir, /static/js/ altından tüm siteyi kapsayamazdı.
 */
function servisCalisaniniKaydet() {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      // Kayıt başarısız olursa uygulama normal site olarak çalışmaya devam
      // eder; kullanıcıya hata göstermeye gerek yok.
    });
  });
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

  tetikleyiciler.forEach((tetik) => {
    tetik.addEventListener("click", () => {
      gorsel.src = tetik.dataset.buyutec;
      gorsel.alt = tetik.dataset.buyutecAlt || "";
      if (baslik) baslik.textContent = tetik.dataset.buyutecBaslik || "";
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
