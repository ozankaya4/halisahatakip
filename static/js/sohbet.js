/**
 * Grup sohbeti — istemci denetleyicisi.
 *
 * Akış:
 *   1. Bu tarayıcıda özel anahtar açık mı? Değilse parola sorulur.
 *   2. Grubun aktif sohbet anahtarı alınır ve açılır.
 *      · Hiç anahtar yoksa (ya da üye ayrıldığı için döndürülmesi
 *        gerekiyorsa) yeni sürüm üretilip tüm üyeler için sarmalanır.
 *      · Paketi olmayan üye varsa (yeni katılan biri) onlar için sarmalanır.
 *   3. Mesajlar çekilir ve tarayıcıda çözülür.
 *   4. Yeni mesajlar için düzenli aralıklarla yoklama yapılır.
 */

import {
  grupAnahtariUret,
  grupAnahtariniAl,
  grupAnahtariniCoz,
  grupAnahtariniSakla,
  grupAnahtariniSarmala,
  mesajCoz,
  mesajSifrele,
  ozelAnahtariAc,
  ozelAnahtariAl,
  depoyuTemizle,
  webcryptoVarMi,
} from "./e2ee.js";
import { jsonIstek } from "./istek.js";

const YOKLAMA_ARALIGI = 6000;

const kok = document.getElementById("sohbet");
if (kok) baslat(kok).catch((hata) => console.error(hata));

async function baslat(kok) {
  const durum = {
    grupId: kok.dataset.grupId,
    kullaniciId: Number(kok.dataset.kullaniciId),
    ozelAnahtar: null,
    anahtarlar: new Map(), // sürüm -> CryptoKey
    aktifSurum: null,
    sonId: 0,
    yoklama: null,
  };

  const bolumler = {
    ortam: document.getElementById("ortam-uyarisi"),
    kilit: document.getElementById("kilit-bolumu"),
    bekleme: document.getElementById("anahtar-bekleme"),
    sohbet: document.getElementById("sohbet-bolumu"),
  };
  const akis = document.getElementById("mesaj-akisi");
  const bilgi = document.getElementById("sohbet-bilgi");

  if (!webcryptoVarMi()) {
    gosterSadece(bolumler, "ortam");
    return;
  }

  // 1. Özel anahtar
  durum.ozelAnahtar = await ozelAnahtariAl(durum.kullaniciId);
  if (!durum.ozelAnahtar) {
    gosterSadece(bolumler, "kilit");
    kilitFormunuBagla(durum, bolumler, () => devam(durum, bolumler, akis, bilgi));
    return;
  }

  await devam(durum, bolumler, akis, bilgi);
}

function gosterSadece(bolumler, ad) {
  Object.entries(bolumler).forEach(([anahtar, el]) => {
    if (el) el.hidden = anahtar !== ad;
  });
}

function kilitFormunuBagla(durum, bolumler, sonra) {
  const form = document.getElementById("kilit-formu");
  if (!form) return;
  const cikti = form.querySelector(".islem-durumu");
  const dugme = form.querySelector("button[type=submit]");

  form.addEventListener("submit", async (olay) => {
    olay.preventDefault();
    const parola = form.querySelector("[name=parola]").value;
    dugme.disabled = true;
    cikti.hidden = false;
    cikti.dataset.tur = "bilgi";
    cikti.textContent = "Kilit açılıyor…";

    try {
      const kayit = await jsonIstek("/sohbet/api/anahtar/");
      if (!kayit.var) {
        window.location.href = "/sohbet/anahtar/";
        return;
      }
      durum.ozelAnahtar = await ozelAnahtariAc(durum.kullaniciId, kayit, parola);
      cikti.hidden = true;
      await sonra();
    } catch (hata) {
      cikti.dataset.tur = "hata";
      cikti.textContent = hata.message;
      dugme.disabled = false;
    }
  });
}

async function devam(durum, bolumler, akis, bilgi) {
  try {
    const hazir = await anahtarlariHazirla(durum, bilgi);
    if (!hazir) {
      gosterSadece(bolumler, "bekleme");
      return;
    }
  } catch (hata) {
    gosterSadece(bolumler, "bekleme");
    const kutu = document.getElementById("bekleme-mesaji");
    if (kutu) kutu.textContent = hata.message;
    return;
  }

  gosterSadece(bolumler, "sohbet");
  gondermeyiBagla(durum, akis);
  kilitlemeyiBagla();

  await mesajlariYukle(durum, akis, false);
  durum.yoklama = setInterval(
    () => mesajlariYukle(durum, akis, true).catch(() => {}),
    YOKLAMA_ARALIGI,
  );
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) mesajlariYukle(durum, akis, true).catch(() => {});
  });
}

/**
 * Grup anahtarlarını hazırlar.
 * Sohbete yazılabilir durumdaysak true döner.
 */
async function anahtarlariHazirla(durum, bilgi) {
  const veri = await jsonIstek(`/sohbet/api/${durum.grupId}/durum/`);

  // Elimizdeki tüm sürümleri aç: geçmiş, anahtar döndükten sonra da okunsun.
  for (const paket of veri.paketlerim || []) {
    if (durum.anahtarlar.has(paket.surum)) continue;
    let anahtar = await grupAnahtariniAl(durum.grupId, paket.surum);
    if (!anahtar) {
      try {
        anahtar = await grupAnahtariniCoz(paket.sarmalanmis, durum.ozelAnahtar);
        await grupAnahtariniSakla(durum.grupId, paket.surum, anahtar);
      } catch {
        continue; // bu sürüm başka bir anahtar çiftiyle sarmalanmış
      }
    }
    durum.anahtarlar.set(paket.surum, anahtar);
  }

  // Aktif anahtar yoksa üret ve herkes için sarmala.
  if (!veri.anahtar) {
    const uygunUyeler = (veri.uyeler || []).filter((u) => u.acik_anahtar);
    if (!uygunUyeler.some((u) => u.id === durum.kullaniciId)) {
      throw new Error("Anahtarın sunucuda görünmüyor. Sayfayı yenilemeyi dene.");
    }

    const yeniAnahtar = await grupAnahtariUret();
    const paketler = [];
    for (const uye of uygunUyeler) {
      paketler.push({
        uye_id: uye.id,
        sarmalanmis: await grupAnahtariniSarmala(yeniAnahtar, uye.acik_anahtar),
      });
    }

    const sonuc = await jsonIstek(`/sohbet/api/${durum.grupId}/anahtar/`, {
      yontem: "POST",
      govde: { surum: veri.sonraki_surum, paketler },
    });

    await grupAnahtariniSakla(durum.grupId, sonuc.surum, yeniAnahtar);
    durum.anahtarlar.set(sonuc.surum, yeniAnahtar);
    durum.aktifSurum = sonuc.surum;
    bilgiYaz(bilgi, veri);
    return true;
  }

  durum.aktifSurum = veri.anahtar.surum;

  // Aktif sürümün anahtarı bizde yoksa, bir üyenin bizim için sarmalaması gerek.
  if (!durum.anahtarlar.has(durum.aktifSurum)) {
    if (!veri.anahtar.sarmalanmis) return false;
    const anahtar = await grupAnahtariniCoz(
      veri.anahtar.sarmalanmis,
      durum.ozelAnahtar,
    );
    await grupAnahtariniSakla(durum.grupId, durum.aktifSurum, anahtar);
    durum.anahtarlar.set(durum.aktifSurum, anahtar);
  }

  // Paketi olmayan üyeler (yeni katılanlar) için sarmalayıp yükleyelim.
  const eksik = veri.eksik_uyeler || [];
  if (eksik.length) {
    const acikHarita = new Map(
      (veri.uyeler || []).filter((u) => u.acik_anahtar).map((u) => [u.id, u.acik_anahtar]),
    );
    const grupAnahtari = durum.anahtarlar.get(durum.aktifSurum);
    const paketler = [];
    for (const uye of eksik) {
      const acik = acikHarita.get(uye.id);
      if (!acik) continue;
      paketler.push({
        uye_id: uye.id,
        sarmalanmis: await grupAnahtariniSarmala(grupAnahtari, acik),
      });
    }
    if (paketler.length) {
      try {
        await jsonIstek(`/sohbet/api/${durum.grupId}/paket/`, {
          yontem: "POST",
          govde: { surum: durum.aktifSurum, paketler },
        });
      } catch {
        /* başka bir üye önce davranmış olabilir; sorun değil */
      }
    }
  }

  bilgiYaz(bilgi, veri);
  return true;
}

function bilgiYaz(bilgi, veri) {
  if (!bilgi) return;
  const eksik = veri.anahtarsiz_uye_sayisi || 0;
  bilgi.textContent = eksik
    ? `${eksik} üye henüz şifreleme parolası belirlemedi; onlar mesajları okuyamaz.`
    : "";
  bilgi.hidden = !eksik;
}

/* ---------------------------------------------------------------------- */
async function mesajlariYukle(durum, akis, artan) {
  const url = artan
    ? `/sohbet/api/${durum.grupId}/mesajlar/?sonra=${durum.sonId}`
    : `/sohbet/api/${durum.grupId}/mesajlar/`;
  const veri = await jsonIstek(url);
  if (!veri.mesajlar.length) return;

  const dipteydi =
    akis.scrollHeight - akis.scrollTop - akis.clientHeight < 80;

  for (const mesaj of veri.mesajlar) {
    if (mesaj.id > durum.sonId) durum.sonId = mesaj.id;
    akis.appendChild(await baloncukYap(durum, mesaj));
  }

  const bos = document.getElementById("akis-bos");
  if (bos) bos.hidden = true;
  if (!artan || dipteydi) akis.scrollTop = akis.scrollHeight;
}

async function baloncukYap(durum, mesaj) {
  const anahtar = durum.anahtarlar.get(mesaj.anahtar_surum);
  let metin;
  let cozulemedi = false;

  if (!anahtar) {
    metin = "Bu mesaj sen gruba katılmadan önce gönderilmiş; okunamıyor.";
    cozulemedi = true;
  } else {
    try {
      metin = await mesajCoz(
        anahtar,
        mesaj.sifreli_metin,
        mesaj.iv,
        durum.grupId,
        mesaj.anahtar_surum,
        mesaj.gonderen_id,
      );
    } catch {
      metin = "Mesaj çözülemedi.";
      cozulemedi = true;
    }
  }

  const satir = document.createElement("li");
  satir.className = "baloncuk";
  if (mesaj.gonderen_id === durum.kullaniciId) satir.classList.add("benim");
  if (cozulemedi) satir.classList.add("cozulemedi");

  const ust = document.createElement("div");
  ust.className = "baloncuk-ust";

  const ad = document.createElement("span");
  ad.className = "baloncuk-ad";
  ad.textContent = mesaj.gonderen_ad;

  const zaman = document.createElement("time");
  zaman.className = "baloncuk-zaman";
  const tarih = new Date(mesaj.zaman);
  zaman.dateTime = mesaj.zaman;
  zaman.textContent = tarih.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

  ust.append(ad, zaman);

  const govde = document.createElement("p");
  govde.className = "baloncuk-metin";
  // textContent kullanıyoruz: çözülen metin hiçbir zaman HTML olarak
  // yorumlanmaz, dolayısıyla mesaj yoluyla XSS mümkün değildir.
  govde.textContent = metin;

  satir.append(ust, govde);
  return satir;
}

function gondermeyiBagla(durum, akis) {
  const form = document.getElementById("mesaj-formu");
  if (!form) return;
  const alan = form.querySelector("[name=metin]");
  const dugme = form.querySelector("button[type=submit]");
  const uyari = form.querySelector(".islem-durumu");

  const gonder = async () => {
    const metin = alan.value.trim();
    if (!metin) return;

    const anahtar = durum.anahtarlar.get(durum.aktifSurum);
    if (!anahtar) return;

    dugme.disabled = true;
    try {
      const paket = await mesajSifrele(
        anahtar,
        metin,
        durum.grupId,
        durum.aktifSurum,
        durum.kullaniciId,
      );
      const yanit = await jsonIstek(`/sohbet/api/${durum.grupId}/mesajlar/`, {
        yontem: "POST",
        govde: { anahtar_surum: durum.aktifSurum, ...paket },
      });

      alan.value = "";
      alan.style.height = "auto";
      uyari.hidden = true;
      if (yanit.mesaj.id > durum.sonId) {
        durum.sonId = yanit.mesaj.id;
        akis.appendChild(await baloncukYap(durum, yanit.mesaj));
        const bos = document.getElementById("akis-bos");
        if (bos) bos.hidden = true;
        akis.scrollTop = akis.scrollHeight;
      }
    } catch (hata) {
      uyari.hidden = false;
      uyari.dataset.tur = "hata";
      uyari.textContent = hata.message;
    } finally {
      dugme.disabled = false;
      alan.focus();
    }
  };

  form.addEventListener("submit", (olay) => {
    olay.preventDefault();
    gonder();
  });

  // Enter gönderir, Shift+Enter alt satıra geçer.
  alan.addEventListener("keydown", (olay) => {
    if (olay.key === "Enter" && !olay.shiftKey) {
      olay.preventDefault();
      gonder();
    }
  });

  alan.addEventListener("input", () => {
    alan.style.height = "auto";
    alan.style.height = Math.min(alan.scrollHeight, 160) + "px";
  });
}

function kilitlemeyiBagla() {
  const dugme = document.getElementById("kilitle-dugmesi");
  if (!dugme) return;
  dugme.addEventListener("click", async () => {
    await depoyuTemizle();
    window.location.reload();
  });
}
