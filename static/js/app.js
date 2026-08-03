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
});

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
