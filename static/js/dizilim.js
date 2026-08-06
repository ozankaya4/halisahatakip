/**
 * Dizilim tahtası — oyuncuları sahada sürükleyerek yerleştirme.
 *
 * Konumlar sahanın YÜZDESİ olarak tutuluyor (0-100), piksel olarak değil:
 * saha telefonda dar, masaüstünde geniş çiziliyor ve yüzde her ikisinde de
 * aynı noktaya denk geliyor.
 *
 * Konumlar CSS özel değişkenleriyle (--x/--y) uygulanıyor. Şablonda
 * style="left:%40" yazılamıyor çünkü CSP satır içi stili engelliyor; ama
 * JS'ten setProperty çağırmak CSP kapsamında değil. Bu yüzden ilk yerleşim
 * de burada yapılıyor: kartlar data-x/data-y ile geliyor, JS bunları
 * göreve çeviriyor.
 *
 * Sürükleme için Pointer Events kullanılıyor. HTML5'in kendi drag-and-drop'u
 * dokunmatik ekranlarda çalışmıyor; pointer olayları fare, parmak ve kalem
 * için aynı kodu çalıştırıyor.
 */

const SINIR = { enAz: 0, enCok: 100 };

/**
 * Takımların yerleşebileceği yatay aralıklar.
 *
 * Bir oyuncu rakip takımın yarısına sürüklenemiyor: iki takım karışınca
 * dizilim okunamaz hâle geliyordu. Aynı aralıklar sunucu tarafında da var
 * (apps/matches/dizilim.py::TAKIM_ARALIKLARI); istemciden gelen konum orada
 * tekrar kırpılıyor.
 */
const TAKIM_ARALIKLARI = {
  a: { enAz: 4, enCok: 47 },
  b: { enAz: 53, enCok: 96 },
};

document.addEventListener("DOMContentLoaded", () => {
  const saha = document.getElementById("saha");
  if (!saha) return;

  const kartlar = Array.from(saha.querySelectorAll(".oyuncu-kart"));
  kartlar.forEach(konumUygula);

  if (saha.hasAttribute("data-duzenlenebilir")) {
    kartlar.forEach((kart) => suruklemeyiBagla(saha, kart));
  }
});

/** data-x/data-y değerlerini CSS değişkenlerine yazar. */
function konumUygula(kart) {
  kart.style.setProperty("--x", `${kart.dataset.x}%`);
  kart.style.setProperty("--y", `${kart.dataset.y}%`);
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
  return kart.classList.contains("takim-a") ? "a" : kart.classList.contains("takim-b") ? "b" : null;
}

/** X konumunu oyuncunun kendi yarısına hapseder. */
function xKirp(deger, kart) {
  const aralik = TAKIM_ARALIKLARI[kartinTakimi(kart)];
  if (!aralik) return kirp(deger);
  return Math.max(aralik.enAz, Math.min(aralik.enCok, deger));
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

    const kutu = saha.getBoundingClientRect();
    if (!kutu.width || !kutu.height) return;

    const x = xKirp(((olay.clientX - kutu.left) / kutu.width) * 100, kart);
    const y = kirp(((olay.clientY - kutu.top) / kutu.height) * 100);

    kart.dataset.x = Math.round(x);
    kart.dataset.y = Math.round(y);
    konumUygula(kart);
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
    const adimlar = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const adim = adimlar[olay.key];
    if (!adim) return;

    const carpan = olay.shiftKey ? 5 : 1;
    kart.dataset.x = xKirp(Number(kart.dataset.x) + adim[0] * carpan, kart);
    kart.dataset.y = kirp(Number(kart.dataset.y) + adim[1] * carpan);
    konumUygula(kart);
    gizlileriGuncelle(kart);
    olay.preventDefault();
  });
}
