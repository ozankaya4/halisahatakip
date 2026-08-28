/**
 * Telefona bildirim izni ve abonelik.
 *
 * Uygulamanın bildirim sistemi eksiksizdi ama tamamen çekmeliydi: kişi maçın
 * 21:30'a alındığını ancak uygulamayı bir dahaki açışında görüyordu, ki çoğu
 * insan için o an zaten arabaya bindiği an. Android kabuğu bildirimler açık
 * üretilmişti; eksik olan tek şey web tarafının izin isteyip abone olmasıydı.
 *
 * İZİN NE ZAMAN İSTENİYOR: yalnızca kullanıcı düğmeye bastığında. Sayfa
 * açılır açılmaz izin istemek, tarayıcıların "kalıcı ret" ile cezalandırdığı
 * bir davranış; bir kez reddedilince bir daha sorulamıyor.
 *
 * İÇE AKTARMA YOK: servis çalışanı bunu ön belleğe alabilsin ve üretimdeki
 * karmalı dosya adlarıyla çevrimdışı çözülme sorunu yaşanmasın diye.
 */

const kok = document.querySelector("[data-bildirim-kutusu]");

if (kok) {
  const dugme = kok.querySelector("[data-bildirim-dugmesi]");
  const durum = kok.querySelector("[data-bildirim-durum]");
  const yaz = (metin) => {
    if (durum) durum.textContent = metin;
  };

  const desteklenir =
    "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

  /** base64url (VAPID açık anahtarı) -> Uint8Array */
  function anahtariCoz(base64) {
    const dolgu = "=".repeat((4 - (base64.length % 4)) % 4);
    const duz = (base64 + dolgu).replace(/-/g, "+").replace(/_/g, "/");
    const ham = atob(duz);
    return Uint8Array.from(ham, (c) => c.charCodeAt(0));
  }

  function csrf() {
    for (const parca of document.cookie ? document.cookie.split(";") : []) {
      const t = parca.trim();
      if (t.startsWith("hst_csrftoken=")) return decodeURIComponent(t.slice(14));
    }
    return "";
  }

  async function gonder(url, govde) {
    const yanit = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(govde || {}),
    });
    if (!yanit.ok) throw new Error("İstek başarısız.");
    return yanit.json();
  }

  async function baslat() {
    if (!desteklenir) {
      kok.hidden = true; // Çalışmayan bir düğme göstermenin anlamı yok.
      return;
    }

    let ayar;
    try {
      ayar = await (await fetch("/bildirimler/push/ayarlar/", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })).json();
    } catch {
      kok.hidden = true;
      return;
    }

    // Sunucuda VAPID anahtarı yoksa bu özellik hiç yok demektir.
    if (!ayar.acik) {
      kok.hidden = true;
      return;
    }
    kok.hidden = false;

    const kayit = await navigator.serviceWorker.ready;
    let abonelik = await kayit.pushManager.getSubscription();

    const tazele = () => {
      if (Notification.permission === "denied") {
        dugme.hidden = true;
        yaz(
          "Bildirimler tarayıcı ayarlarından engellenmiş. Açmak için site " +
            "ayarlarından bildirimlere izin vermen gerekiyor.",
        );
        return;
      }
      dugme.hidden = false;
      dugme.textContent = abonelik ? "Bildirimleri kapat" : "Bildirimleri aç";
      yaz(
        abonelik
          ? "Maç saati değiştiğinde ya da yoklama açıldığında telefonuna bildirim gelecek."
          : "Maç değişikliklerini kaçırmamak için bildirimleri açabilirsin.",
      );
    };

    tazele();

    dugme.addEventListener("click", async () => {
      dugme.disabled = true;
      try {
        if (abonelik) {
          const uc = abonelik.endpoint;
          await abonelik.unsubscribe();
          await gonder("/bildirimler/push/cik/", { endpoint: uc });
          abonelik = null;
          yaz("Bildirimler kapatıldı.");
        } else {
          // İzin ancak kullanıcı tıkladıktan sonra isteniyor.
          const izin = await Notification.requestPermission();
          if (izin !== "granted") {
            tazele();
            return;
          }
          abonelik = await kayit.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: anahtariCoz(ayar.acik_anahtar),
          });
          await gonder("/bildirimler/push/abone/", abonelik.toJSON());
          yaz("Açıldı. Bu cihaza bildirim gelecek.");
        }
        tazele();
      } catch {
        yaz("İşlem tamamlanamadı. Biraz sonra tekrar dene.");
      } finally {
        dugme.disabled = false;
      }
    });
  }

  baslat().catch(() => {
    kok.hidden = true;
  });
}
