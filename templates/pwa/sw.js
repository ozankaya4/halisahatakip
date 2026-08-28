{% load static %}/*
 * Halısaha Defteri — servis çalışanı (service worker).
 *
 * GİZLİLİK KURALI — bu dosyada en önemli şey:
 * Kullanıcıya ait hiçbir şey önbelleğe ALINMAZ. Yalnızca herkese açık,
 * içeriği adında karma (hash) taşıyan statik dosyalar saklanır.
 *
 * Sebebi: uygulama telefonun ana ekranına kuruluyor ve cihaz paylaşılabiliyor.
 * Sayfalar önbelleğe alınsaydı, çıkış yapmış ya da başka biri girmiş olsa bile
 * bir önceki kullanıcının maç kadroları, grup adları ve sohbet sayfaları
 * diskte kalırdı. Uçtan uca şifreli sohbetin anlamı da zayıflardı: mesajlar
 * şifreli dursa bile kimin hangi grupta olduğu diskte kalırdı.
 *
 * Bu yüzden:
 *   /static/...  -> önbellekten (adında karma var, asla değişmez)
 *   gezinme      -> önce ağ, ağ yoksa "çevrimdışı" sayfası
 *   diğer her şey-> hiç dokunma, doğrudan ağa gitsin
 */

const SURUM = "3";
const ONBELLEK_ADI = `halisaha-statik-v${SURUM}`;
const CEVRIMDISI = "{% url 'core:cevrimdisi' %}";

// Kurulumda saklanacaklar. Hepsi herkese açık ve kullanıcıdan bağımsız.
//
// DİKKAT: Çevrimdışı sayfası ÇEREZSİZ indiriliyor (credentials: "omit").
// Varsayılan "same-origin" ile indirildiğinde sunucu sayfayı o anki
// kullanıcı için render ediyor ve diske düşen kopyada CSRF jetonu,
// kullanıcı kimliği ve bildirim sayısı kalıyordu. Sayfanın kendisi de
// artık base.html'i genişletmiyor; iki koruma birbirini yedekliyor.
const ON_YUKLENECEK = [
  new Request(CEVRIMDISI, { credentials: "omit", cache: "reload" }),
  "{% static 'css/defter.css' %}",
  "{% static 'css/yazitipi.css' %}",
  "{% static 'js/app.js' %}",
  // Çevrimdışı sayfası bunu çalıştırıyor: kullanıcı açtıysa saklanan
  // sıradaki maçı gösteriyor. İçe aktarması yok, tek başına çalışıyor.
  "{% static 'js/cevrimdisi.js' %}",
  "{% static 'fonts/fraunces-latin.woff2' %}",
  "{% static 'fonts/fraunces-latin-ext.woff2' %}",
  "{% static 'fonts/plex-sans-latin.woff2' %}",
  "{% static 'fonts/plex-sans-latin-ext.woff2' %}",
  "{% static 'img/favicon.svg' %}",
  "{% static 'img/ikon-192.png' %}",
];

self.addEventListener("install", (olay) => {
  olay.waitUntil(
    caches
      .open(ONBELLEK_ADI)
      // Tek bir dosya inmezse kurulumun tamamı çökmesin.
      .then((onbellek) =>
        Promise.allSettled(ON_YUKLENECEK.map((yol) => onbellek.add(yol))),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (olay) => {
  olay.waitUntil(
    caches
      .keys()
      .then((adlar) =>
        Promise.all(
          adlar
            .filter((ad) => ad.startsWith("halisaha-statik-") && ad !== ONBELLEK_ADI)
            .map((ad) => caches.delete(ad)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

/** Bu istek önbelleğe alınabilir mi? Kural: yalnızca /static/ altı. */
function statikMi(url) {
  return url.origin === self.location.origin && url.pathname.startsWith("{% get_static_prefix %}");
}

self.addEventListener("fetch", (olay) => {
  const istek = olay.request;

  // Yalnızca GET. POST/PUT/DELETE asla önbelleğe girmez.
  if (istek.method !== "GET") return;

  const url = new URL(istek.url);
  if (url.origin !== self.location.origin) return; // dış kaynaklara karışma

  // --- Statik dosyalar: önce önbellek -------------------------------------
  // Dosya adlarında karma olduğu için içerik değişince ad da değişiyor;
  // eski sürümün sunulması mümkün değil.
  if (statikMi(url)) {
    olay.respondWith(
      caches.match(istek).then(
        (bulunan) =>
          bulunan ||
          fetch(istek).then((yanit) => {
            if (yanit.ok) {
              const kopya = yanit.clone();
              caches.open(ONBELLEK_ADI).then((o) => o.put(istek, kopya));
            }
            return yanit;
          }),
      ),
    );
    return;
  }

  // --- Sayfa gezinmeleri: önce ağ, olmazsa çevrimdışı sayfası -------------
  // Yanıt ASLA saklanmıyor; yalnızca ağ tamamen yoksa sabit bir bilgi
  // sayfası gösteriliyor.
  if (istek.mode === "navigate") {
    olay.respondWith(
      fetch(istek).catch(() =>
        caches
        .match(CEVRIMDISI, { ignoreVary: true })
        .then((sayfa) => sayfa || Response.error()),
      ),
    );
    return;
  }

  // --- Geri kalan her şey ------------------------------------------------
  // Fotoğraflar (/dosya/...), sohbet API'si, formlar: dokunmuyoruz.
  // respondWith çağırmadığımız için tarayıcı isteği normal şekilde yapıyor.
});

/* =========================================================================
   Telefona bildirim (Web Push)

   Uygulamanın bildirimleri eksiksizdi ama çekmeliydi: kişi maçın saatinin
   değiştiğini ancak uygulamayı bir dahaki açışında öğreniyordu. Burası o
   bildirimi telefonun kilit ekranına çıkarıyor.

   İÇERİK NOTU: sohbet bildiriminde metin YOK ve olamaz — sunucu uçtan uca
   şifreli mesajı okuyamıyor, dolayısıyla gönderemiyor. Yalnızca "yeni mesaj
   var" deniyor; metin, uygulama açılıp mesaj tarayıcıda çözülünce görünüyor.
   Maç ve yoklama bildirimleri metin taşıyor, çünkü onu sunucu yazıyor.
   ====================================================================== */
self.addEventListener("push", (olay) => {
  let veri = {};
  try {
    veri = olay.data ? olay.data.json() : {};
  } catch {
    veri = {};
  }

  const baslik = veri.baslik || "Halısaha Defteri";
  olay.waitUntil(
    self.registration.showNotification(baslik, {
      body: veri.mesaj || "",
      icon: "{% static 'img/ikon-192.png' %}",
      badge: "{% static 'img/ikon-192.png' %}",
      // Aynı türden art arda gelen bildirimler yığılmasın: sonuncusu
      // öncekinin yerine geçsin.
      tag: veri.etiket || "halisaha",
      renotify: true,
      data: { adres: veri.adres || "/panel/" },
    }),
  );
});

/* Bildirime dokununca: uygulama zaten açıksa o sekmeye geç, değilse aç. */
self.addEventListener("notificationclick", (olay) => {
  olay.notification.close();
  const adres = (olay.notification.data && olay.notification.data.adres) || "/panel/";

  olay.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((pencereler) => {
        for (const pencere of pencereler) {
          // Aynı köken: yeni sekme açmak yerine var olanı öne al.
          if (new URL(pencere.url).origin === self.location.origin) {
            return pencere.focus().then((p) => (p.navigate ? p.navigate(adres) : p));
          }
        }
        return self.clients.openWindow(adres);
      }),
  );
});
