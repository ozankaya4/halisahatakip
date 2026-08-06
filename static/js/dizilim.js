/**
 * Dizilim tahtası — oyuncuları sahada sürükleyerek yerleştirme.
 *
 * KONUM MODELİ
 * Konumlar her zaman YATAY sahanın yüzdesi olarak saklanır (0-100):
 *   x = sahanın uzun ekseni; takımları ayıran eksen (A: 4-47, B: 53-96)
 *   y = sahanın kısa ekseni
 * Aynı aralıklar sunucuda da var: apps/matches/dizilim.py::TAKIM_ARALIKLARI
 *
 * DİKEY MOD (telefon)
 * Dar ekranda saha dikey çiziliyor ve eksenler yer değiştirerek gösteriliyor:
 * ekranda sol/sağ ← y, üst/alt ← x. Yani A Takımı üstte, B Takımı altta.
 *
 * Önemli olan şu: SAKLANAN VERİ DEĞİŞMİYOR. Telefonda kurulan dizilim
 * masaüstünde de doğru görünür, tersi de geçerli. Sahayı CSS ile döndürmek
 * (rotate) yerine yalnızca eşleme değiştiriliyor; döndürseydik oyuncu
 * adları da yan yatardı.
 *
 * Dikey mi değil mi kararı BURADA veriliyor ve saha öğesine "saha-dikey"
 * sınıfı olarak yazılıyor; CSS de o sınıfa bakıyor. CSS'te ayrı bir medya
 * sorgusu olsaydı sınır değerlerde JS ile CSS farklı düşünebilirdi.
 *
 * Sürükleme Pointer Events ile: HTML5'in kendi drag-and-drop'u dokunmatik
 * ekranlarda çalışmıyor, pointer olayları fare/parmak/kalem için aynı kod.
 */

const SINIR = { enAz: 0, enCok: 100 };

const TAKIM_ARALIKLARI = {
  a: { enAz: 4, enCok: 47 },
  b: { enAz: 53, enCok: 96 },
};

// Sahanın dikey çizileceği ekran genişliği. defter.css'teki mobil kırılma
// noktasıyla aynı olmalı.
const DIKEY_SORGU = "(max-width: 640px)";

document.addEventListener("DOMContentLoaded", () => {
  const saha = document.getElementById("saha");
  if (!saha) return;

  const kartlar = Array.from(saha.querySelectorAll(".oyuncu-kart"));
  const sorgu = window.matchMedia(DIKEY_SORGU);

  const moduUygula = () => {
    saha.classList.toggle("saha-dikey", sorgu.matches);
    // Eksen eşlemesi değiştiği için konumlar yeniden yazılmalı.
    kartlar.forEach((kart) => konumUygula(kart, saha));
  };

  moduUygula();
  // Ekran döndürüldüğünde ya da pencere yeniden boyutlandığında.
  sorgu.addEventListener("change", moduUygula);

  if (saha.hasAttribute("data-duzenlenebilir")) {
    kartlar.forEach((kart) => suruklemeyiBagla(saha, kart));
  }
});

/** Saha şu anda dikey mi çiziliyor? */
function dikeyMi(saha) {
  return saha.classList.contains("saha-dikey");
}

/**
 * data-x/data-y değerlerini CSS değişkenlerine yazar.
 * Dikey modda eksenler yer değiştirir.
 */
function konumUygula(kart, saha) {
  const x = kart.dataset.x;
  const y = kart.dataset.y;
  if (dikeyMi(saha)) {
    kart.style.setProperty("--x", `${y}%`);
    kart.style.setProperty("--y", `${x}%`);
  } else {
    kart.style.setProperty("--x", `${x}%`);
    kart.style.setProperty("--y", `${y}%`);
  }
}

/** Formdaki gizli alanları güncel konumla eşitler. */
function gizlileriGuncelle(kart) {
  const id = kart.dataset.oyuncu;
  const x = kart.querySelector(`input[name="x_${id}"]`);
  const y = kart.querySelector(`input[name="y_${id}"]`);
  if (x) x.value = kart.dataset.x;
  if (y) y.value = kart.dataset.y;
}

function kirp(deger) {
  return Math.max(SINIR.enAz, Math.min(SINIR.enCok, deger));
}

/** Kartın takımını sınıf adından okur (takim-a / takim-b). */
function kartinTakimi(kart) {
  return kart.classList.contains("takim-a")
    ? "a"
    : kart.classList.contains("takim-b")
      ? "b"
      : null;
}

/**
 * Saklanan x'i oyuncunun kendi yarısına hapseder.
 * Hangi modda olursak olalım kısıt aynı alan üzerinde: x takımları ayıran
 * eksen. Dikeyde bu ekranda yukarı/aşağı sınırı olarak görünür.
 */
function xKirp(deger, kart) {
  const aralik = TAKIM_ARALIKLARI[kartinTakimi(kart)];
  if (!aralik) return kirp(deger);
  return Math.max(aralik.enAz, Math.min(aralik.enCok, deger));
}

/** İmleç konumundan saklanacak {x, y} değerlerini üretir. */
function imlecdenKonum(olay, saha, kart) {
  const kutu = saha.getBoundingClientRect();
  if (!kutu.width || !kutu.height) return null;

  const yatayOran = ((olay.clientX - kutu.left) / kutu.width) * 100;
  const dikeyOran = ((olay.clientY - kutu.top) / kutu.height) * 100;

  // Dikey modda ekranın dikey ekseni saklanan x'e, yatay ekseni y'ye denk.
  return dikeyMi(saha)
    ? { x: xKirp(dikeyOran, kart), y: kirp(yatayOran) }
    : { x: xKirp(yatayOran, kart), y: kirp(dikeyOran) };
}

function suruklemeyiBagla(saha, kart) {
  let suruklyor = false;

  kart.addEventListener("pointerdown", (olay) => {
    // Farede yalnızca sol tuş; parmak ve kalemde düğme kontrolü yok.
    if (olay.pointerType === "mouse" && olay.button !== 0) return;

    suruklyor = true;
    kart.setPointerCapture(olay.pointerId);
    kart.classList.add("suruklerken");
    // Sayfanın kayması ve metin seçilmesi engelleniyor.
    olay.preventDefault();
  });

  kart.addEventListener("pointermove", (olay) => {
    if (!suruklyor) return;

    const konum = imlecdenKonum(olay, saha, kart);
    if (!konum) return;

    kart.dataset.x = Math.round(konum.x);
    kart.dataset.y = Math.round(konum.y);
    konumUygula(kart, saha);
    gizlileriGuncelle(kart);
  });

  const bitir = (olay) => {
    if (!suruklyor) return;
    suruklyor = false;
    kart.classList.remove("suruklerken");
    if (kart.hasPointerCapture(olay.pointerId)) {
      kart.releasePointerCapture(olay.pointerId);
    }
  };

  kart.addEventListener("pointerup", bitir);
  kart.addEventListener("pointercancel", bitir);

  // Klavyeyle de taşınabilsin: fare kullanamayan biri dizilimi
  // düzenleyemez hâle gelmesin. Shift ile büyük adım.
  kart.addEventListener("keydown", (olay) => {
    // Ok tuşu kartı EKRANDA göründüğü yöne taşımalı; bu yüzden dikey modda
    // hangi alanı değiştirdikleri de yer değiştiriyor.
    const ekranAdimlari = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const adim = ekranAdimlari[olay.key];
    if (!adim) return;

    const carpan = olay.shiftKey ? 5 : 1;
    const [ekranYatay, ekranDikey] = adim;

    // Ekran yönünü saklanan alanlara çevir.
    const dx = dikeyMi(saha) ? ekranDikey : ekranYatay;
    const dy = dikeyMi(saha) ? ekranYatay : ekranDikey;

    kart.dataset.x = xKirp(Number(kart.dataset.x) + dx * carpan, kart);
    kart.dataset.y = kirp(Number(kart.dataset.y) + dy * carpan);
    konumUygula(kart, saha);
    gizlileriGuncelle(kart);
    olay.preventDefault();
  });
}
