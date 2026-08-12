/*
  Dizilim görselini kaydetme ve paylaşma.

  Görsel sunucuda çiziliyor (apps/matches/gorsel.py); burada yapılan tek şey
  onu getirip doğru yere yollamak:

    telefon/tablet : cihazın paylaşım sayfası (Instagram, WhatsApp, "Fotoğrafı
                     Kaydet" hepsi orada)
    bilgisayar     : doğrudan indirme

  Neden telefonda önce indirip sonra paylaşmıyoruz: iOS'ta indirilen dosya
  galeriye değil Dosyalar'a gidiyor ve kullanıcı iki kopya görüyor. Paylaşım
  sayfasındaki "Fotoğrafı Kaydet" ise doğrudan galeriye atıyor.

  Bağlantılar HTML'de gerçek <a download> olarak duruyor; bu dosya hiç
  yüklenmezse tarayıcı görseli yine de indirir.
*/

const kutu = document.getElementById("gorsel-secim");
const acmaDugmesi = document.querySelector("[data-gorsel-ac]");

if (kutu && acmaDugmesi) {
  const durumSatiri = kutu.querySelector("[data-gorsel-durum]");
  const secenekler = Array.from(kutu.querySelectorAll("[data-gorsel-yon]"));

  // Getirilen görseller yön başına saklanıyor: aynı yönü ikinci kez
  // isteyen beklemiyor.
  const onbellek = new Map();

  const dokunmatik = window.matchMedia("(pointer: coarse)").matches;

  function durum(yazi) {
    if (durumSatiri) durumSatiri.textContent = yazi || "";
  }

  function dosyaAdi(baglanti) {
    const adres = new URL(baglanti.href, window.location.origin);
    return adres.pathname.split("/").pop() || "dizilim.png";
  }

  async function gorseliGetir(baglanti) {
    const anahtar = baglanti.dataset.gorselYon;
    if (!onbellek.has(anahtar)) {
      onbellek.set(
        anahtar,
        fetch(baglanti.href, { credentials: "same-origin" }).then((yanit) => {
          if (!yanit.ok) throw new Error("Görsel alınamadı");
          return yanit.blob();
        })
      );
    }
    return onbellek.get(anahtar);
  }

  function indir(veri, ad) {
    const adres = URL.createObjectURL(veri);
    const gecici = document.createElement("a");
    gecici.href = adres;
    gecici.download = ad;
    document.body.appendChild(gecici);
    gecici.click();
    gecici.remove();
    // Tarayıcının indirmeyi başlatmasına zaman tanınıyor.
    setTimeout(() => URL.revokeObjectURL(adres), 20000);
  }

  acmaDugmesi.addEventListener("click", () => {
    durum("");
    if (typeof kutu.showModal === "function") {
      kutu.showModal();
    } else {
      kutu.setAttribute("open", "");
    }
    // Kutu açılır açılmaz iki yön de arka planda hazırlanıyor. iOS'ta
    // paylaşım çağrısı dokunmadan hemen sonra gelmezse reddediliyor;
    // görsel hazırsa tıklama anında paylaşılabiliyor.
    secenekler.forEach((baglanti) => {
      gorseliGetir(baglanti).catch(() => {});
    });
  });

  secenekler.forEach((baglanti) => {
    baglanti.addEventListener("click", async (olay) => {
      // Paylaşımı deneyeceksek tarayıcının kendi indirmesi devreye girmesin.
      if (!dokunmatik || !navigator.canShare) return;

      olay.preventDefault();
      durum("Görsel hazırlanıyor…");

      let veri;
      try {
        veri = await gorseliGetir(baglanti);
      } catch (hata) {
        durum("Görsel hazırlanamadı. Tekrar dene.");
        return;
      }

      const ad = dosyaAdi(baglanti);
      const dosya = new File([veri], ad, { type: "image/png" });

      if (!navigator.canShare({ files: [dosya] })) {
        indir(veri, ad);
        durum("Görsel indirildi.");
        return;
      }

      try {
        await navigator.share({ files: [dosya] });
        durum("");
        kutu.close();
      } catch (hata) {
        // Kullanıcı vazgeçtiyse sessiz kalınıyor; paylaşım reddedildiyse
        // (iOS'ta dokunma izni düşmüş olabilir) indirmeye düşülüyor.
        if (hata && hata.name === "AbortError") {
          durum("");
          return;
        }
        indir(veri, ad);
        durum("Paylaşım açılamadı, görsel indirildi.");
      }
    });
  });
}
