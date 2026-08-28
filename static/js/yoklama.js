/**
 * Yoklama yanıtını zayıf bağlantıda kuyruğa alır.
 *
 * NEDEN VAR: sahanın önünde çekmezken "Geliyorum" demek düpedüz
 * başarısız oluyordu — form gönderiliyor, tarayıcı hata sayfası gösteriyor,
 * yanıt hiçbir yere yazılmıyordu. Oysa yoklama tam da orada, son dakikada
 * veriliyor.
 *
 * Yanıt artık önce fetch ile gönderiliyor; ağ yoksa cihazda bekletiliyor ve
 * bağlantı gelince tekrar deneniyor.
 *
 * CSRF JETONU TAZELİĞİ — buradaki asıl incelik:
 * Beklemiş bir isteği saklanmış jetonla göndermek çalışmaz. Django'nun CSRF
 * jetonu oturuma bağlı; kullanıcı arada çıkış yapıp girerse ya da oturum
 * yenilenirse eski jeton reddedilir ve yanıt sessizce kaybolur — yani
 * özelliğin çözmeye çalıştığı sorunun aynısı, daha sinsi hâli.
 *
 * Bu yüzden jeton KUYRUĞA YAZILMIYOR. Tekrar denenirken çerezden O ANKİ
 * jeton okunuyor. Çerez yoksa (çıkış yapılmış) kuyruk temizleniyor: başka
 * birinin oturumunda yanıt göndermek, kaybolan yanıttan çok daha kötü olurdu.
 *
 * İÇE AKTARMA YOK: servis çalışanı bunu ön belleğe alabilsin diye.
 */

const KUYRUK_ANAHTARI = "halisaha-yoklama-kuyrugu";

function csrfJetonu() {
  for (const parca of document.cookie ? document.cookie.split(";") : []) {
    const t = parca.trim();
    if (t.startsWith("hst_csrftoken=")) return decodeURIComponent(t.slice(14));
  }
  return "";
}

function kuyrugoOku() {
  try {
    const ham = localStorage.getItem(KUYRUK_ANAHTARI);
    return ham ? JSON.parse(ham) : [];
  } catch {
    return [];
  }
}

function kuyrugaYaz(kuyruk) {
  try {
    if (kuyruk.length) localStorage.setItem(KUYRUK_ANAHTARI, JSON.stringify(kuyruk));
    else localStorage.removeItem(KUYRUK_ANAHTARI);
  } catch {
    // Depolama kapalıysa kuyruk tutulamaz; çevrimiçi gönderim yine çalışıyor.
  }
}

/** Tek bir yanıtı gönderir. Ağ hatasında false döner. */
async function gonder(kayit) {
  const jeton = csrfJetonu();
  if (!jeton) throw new Error("oturum-yok");

  const govde = new URLSearchParams();
  govde.set("yanit", kayit.yanit);
  govde.set("csrfmiddlewaretoken", jeton);

  const yanit = await fetch(kayit.adres, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "X-CSRFToken": jeton,
    },
    body: govde.toString(),
    redirect: "follow",
  });
  return yanit.ok;
}

/** Bekleyenleri sırayla dener. Ağ hâlâ yoksa kuyrukta bırakır. */
async function kuyrugoBosalt(durumYaz) {
  let kuyruk = kuyrugoOku();
  if (!kuyruk.length) return;

  if (!csrfJetonu()) {
    // Çıkış yapılmış: başkasının oturumunda yanıt göndermektense kuyruğu at.
    kuyrugaYaz([]);
    return;
  }

  const kalan = [];
  for (const kayit of kuyruk) {
    try {
      const oldu = await gonder(kayit);
      if (!oldu) kalan.push(kayit);
    } catch {
      kalan.push(kayit);
    }
  }
  kuyrugaYaz(kalan);

  if (!kalan.length && durumYaz) {
    durumYaz("Bağlantı geldi, yanıtın kaydedildi.");
    // Sayaçlar sunucudan geliyor; sayfayı tazelemek en dürüst gösterim.
    setTimeout(() => window.location.reload(), 900);
  }
}

const form = document.querySelector("[data-yoklama-formu]");

if (form) {
  const durum = form.querySelector("[data-yoklama-durum]");
  const durumYaz = (metin) => {
    if (durum) {
      durum.textContent = metin;
      durum.hidden = !metin;
    }
  };

  form.addEventListener("submit", async (olay) => {
    // Hangi düğmeye basıldığı submitter'dan geliyor; formda üç düğme var.
    const secim = olay.submitter && olay.submitter.value;
    if (!secim) return; // beklenmedik durum: tarayıcıya bırak

    olay.preventDefault();
    const kayit = { adres: form.action, yanit: secim, zaman: Date.now() };

    try {
      if (await gonder(kayit)) {
        window.location.reload();
        return;
      }
      durumYaz("Yanıtın kaydedilemedi, birazdan tekrar denenecek.");
    } catch {
      durumYaz(
        "Bağlantı yok. Yanıtın telefonunda bekliyor ve internet gelince " +
          "kendiliğinden gönderilecek.",
      );
    }

    // Aynı maç için tek kayıt yeter; son seçim geçerli.
    const kuyruk = kuyrugoOku().filter((k) => k.adres !== kayit.adres);
    kuyruk.push(kayit);
    kuyrugaYaz(kuyruk);
  });

  // Sayfa açılışında ve bağlantı geri geldiğinde bekleyenleri dene.
  kuyrugoBosalt(durumYaz).catch(() => {});
  window.addEventListener("online", () => kuyrugoBosalt(durumYaz).catch(() => {}));
}
