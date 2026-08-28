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
  acikAnahtariDenetle,
  parmakIziniSabitle,
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
    // Üye kimliği -> anahtar denetimi (bkz. uyeleriDenetle)
    denetimler: new Map(),
    uyeler: [],
  };

  const bolumler = {
    ortam: document.getElementById("ortam-uyarisi"),
    kilit: document.getElementById("kilit-bolumu"),
    bekleme: document.getElementById("anahtar-bekleme"),
    sohbet: document.getElementById("sohbet-bolumu"),
  };
  const akis = document.getElementById("mesaj-akisi");
  const bilgi = document.getElementById("sohbet-bilgi");
  const anahtarUyarisi = document.getElementById("anahtar-uyarisi");
  const izListesi = document.getElementById("parmak-izi-listesi");

  bildirmeyiBagla(durum, akis);

  if (!webcryptoVarMi()) {
    gosterSadece(bolumler, "ortam");
    return;
  }

  // 1. Özel anahtar
  durum.ozelAnahtar = await ozelAnahtariAl(durum.kullaniciId);
  if (!durum.ozelAnahtar) {
    gosterSadece(bolumler, "kilit");
    kilitFormunuBagla(durum, bolumler, () =>
      devam(durum, bolumler, akis, bilgi, anahtarUyarisi, izListesi),
    );
    return;
  }

  await devam(durum, bolumler, akis, bilgi, anahtarUyarisi, izListesi);
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

async function devam(durum, bolumler, akis, bilgi, anahtarUyarisi, izListesi) {
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
  uyariYaz(durum, anahtarUyarisi);
  parmakIzleriniYaz(durum, izListesi);
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

  // Sunucunun verdiği her açık anahtarı, daha önce gördüğümüzle karşılaştır.
  // Sarmalama kararı bundan sonra bu denetimin sonucuna göre veriliyor.
  durum.denetimler = await uyeleriDenetle(veri.uyeler || []);
  durum.uyeler = veri.uyeler || [];

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
    // Anahtarı değişmiş üye ATLANIYOR: grup anahtarı ona sarmalanmıyor.
    // Kendimiz her hâlükârda listede kalıyoruz, yoksa ürettiğimiz anahtarı
    // biz de açamayız.
    const uygunUyeler = (veri.uyeler || []).filter(
      (u) =>
        u.acik_anahtar &&
        (u.id === durum.kullaniciId ||
          durum.denetimler.get(u.id)?.durum !== "degisti"),
    );
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
      // Anahtarı değişmiş üyeyi ATLA, ama diğerlerini yüklemeye devam et.
      // Tek şüpheli üye yüzünden bütün grubun sohbeti durmamalı.
      if (durum.denetimler.get(uye.id)?.durum === "degisti") continue;
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

/**
 * Her üyenin açık anahtarını sabitlemeye karşı denetler.
 *
 * Dönen harita: üyeId -> {durum, parmakIzi, sabit, sunucununDedigi}
 * Anahtarı olmayan üye haritaya girmiyor; denetlenecek bir şey yok.
 */
async function uyeleriDenetle(uyeler) {
  const sonuc = new Map();
  for (const uye of uyeler) {
    if (!uye.acik_anahtar) continue;
    const denetim = await acikAnahtariDenetle(uye.id, uye.acik_anahtar);
    sonuc.set(uye.id, { ...denetim, sunucununDedigi: uye.parmak_izi || "" });
  }
  return sonuc;
}

/**
 * Anahtarı değişmiş üyeler için uyarı şeridi.
 *
 * Sunucunun bildirdiği sıfırlama kaydı varsa dili yumuşak: parolasını unutan
 * biri anahtarını sıfırladığında bu olağan. Kayıt YOKSA dil sert, çünkü
 * sebepsiz değişen anahtar tam olarak saldırının şekli.
 */
function uyariYaz(durum, kutu) {
  if (!kutu) return;
  kutu.replaceChildren();

  const degisenler = durum.uyeler.filter(
    (u) => durum.denetimler.get(u.id)?.durum === "degisti",
  );
  if (!degisenler.length) {
    kutu.hidden = true;
    return;
  }
  kutu.hidden = false;

  for (const uye of degisenler) {
    const d = durum.denetimler.get(uye.id);
    const satir = document.createElement("div");
    satir.className = "anahtar-uyarisi";

    const baslik = document.createElement("p");
    const kalin = document.createElement("strong");
    kalin.textContent = `${uye.ad} adlı üyenin şifreleme anahtarı değişti.`;
    baslik.append(kalin);
    satir.append(baslik);

    const aciklama = document.createElement("p");
    aciklama.className = "kucuk";
    if (uye.son_sifirlama) {
      const t = new Date(uye.son_sifirlama);
      aciklama.textContent =
        `Sunucuya göre ${t.toLocaleDateString("tr-TR")} tarihinde anahtarını ` +
        "sıfırlamış. Şifreleme parolasını unutan biri için bu olağan. Yine de " +
        "kabul etmeden önce yeni parmak izini kendisine sorman en doğrusu.";
    } else {
      aciklama.textContent =
        "Bu değişikliğin arkasında kayıtlı bir sıfırlama YOK. Anahtarı " +
        "kendisi yenilemediyse, mesajları okumaya çalışan biri olabilir. " +
        "Kabul etmeden önce mutlaka kendisiyle konuş.";
    }
    satir.append(aciklama);

    const izler = document.createElement("p");
    izler.className = "kucuk parmak-izi";
    izler.textContent = `Yeni parmak izi: ${d.parmakIzi}`;
    satir.append(izler);

    const dugme = document.createElement("button");
    dugme.type = "button";
    dugme.className = "dugme dugme-kucuk";
    dugme.textContent = "Kendisiyle doğruladım, yeni anahtarı kabul et";
    dugme.addEventListener("click", async () => {
      dugme.disabled = true;
      await parmakIziniSabitle(uye.id, d.parmakIzi);
      window.location.reload();
    });
    satir.append(dugme);

    kutu.append(satir);
  }
}

/** Üyeler ve parmak izleri listesi — yüz yüze doğrulama için. */
function parmakIzleriniYaz(durum, liste) {
  if (!liste) return;
  liste.replaceChildren();

  for (const uye of durum.uyeler) {
    const d = durum.denetimler.get(uye.id);
    const satir = document.createElement("li");

    const ad = document.createElement("span");
    ad.className = "parmak-izi-ad";
    ad.textContent = uye.id === durum.kullaniciId ? `${uye.ad} (sen)` : uye.ad;
    satir.append(ad);

    const iz = document.createElement("code");
    iz.className = "parmak-izi";
    // HER ZAMAN yerel hesaplanan değer; sunucunun gönderdiği değil.
    iz.textContent = d ? d.parmakIzi : "anahtarı yok";
    satir.append(iz);

    if (d && d.durum === "degisti") {
      const rozet = document.createElement("span");
      rozet.className = "rozet rozet-kiremit";
      rozet.textContent = "değişti";
      satir.append(rozet);
    }
    liste.append(satir);
  }
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

  // Bildir düğmesi yalnızca başkasının çözülebilmiş mesajında.
  // Kendi mesajını bildirmenin anlamı yok; çözülemeyen mesajda da
  // gönderilecek bir metin yok.
  if (mesaj.gonderen_id !== durum.kullaniciId && !cozulemedi) {
    const bildir = document.createElement("button");
    bildir.type = "button";
    bildir.className = "baloncuk-bildir";
    bildir.textContent = "Bildir";
    bildir.setAttribute("aria-label", `${mesaj.gonderen_ad} mesajını bildir`);
    bildir.dataset.mesajId = String(mesaj.id);
    // Çözülmüş metin burada duruyor: sunucu şifreli mesajı açamadığı için
    // şikâyette metni bildiren kişinin cihazı gönderiyor.
    bildir.dataset.metin = metin;
    satir.append(bildir);
  }

  return satir;
}

/**
 * Mesaj şikâyeti.
 *
 * Akışa tek bir dinleyici bağlanıyor (olay yetkilendirme): baloncuklar
 * sürekli yeniden üretildiği için her birine ayrı dinleyici bağlamak
 * hem gereksiz hem sızıntı kaynağı olurdu.
 *
 * Sunucu şifreli mesajı açamadığından, gönderilen metin baloncuğun
 * üzerinde duran çözülmüş hâli. Kullanıcı kendi isteğiyle iletiyor.
 */
function bildirmeyiBagla(durum, akis) {
  const kutu = document.getElementById("bildir-kutusu");
  if (!akis || !kutu) return;

  const form = kutu.querySelector("form[data-bildir-formu]");
  const durumSatiri = kutu.querySelector("[data-bildir-durum]");
  const onizleme = kutu.querySelector("[data-bildir-onizleme]");
  let secili = null;

  akis.addEventListener("click", (olay) => {
    const dugme = olay.target.closest(".baloncuk-bildir");
    if (!dugme) return;

    secili = { id: dugme.dataset.mesajId, metin: dugme.dataset.metin };
    onizleme.textContent = secili.metin;
    durumSatiri.textContent = "";
    form.reset();

    if (typeof kutu.showModal === "function") kutu.showModal();
    else kutu.setAttribute("open", "");
  });

  form.addEventListener("submit", async (olay) => {
    olay.preventDefault();
    if (!secili) return;

    const veri = new FormData(form);
    const sebep = veri.get("sebep");
    if (!sebep) {
      durumSatiri.textContent = "Bir sebep seç.";
      return;
    }

    durumSatiri.textContent = "Gönderiliyor…";
    try {
      const sonuc = await jsonIstek(`/bildir/sohbet/${durum.grupId}/bildir/`, {
        yontem: "POST",
        govde: {
          mesaj_id: Number(secili.id),
          sebep,
          aciklama: veri.get("aciklama") || "",
          metin: secili.metin,
        },
      });
      durumSatiri.textContent = sonuc.zaten
        ? "Bu mesajı zaten bildirmiştin."
        : "Bildirimin yöneticiye iletildi.";
      setTimeout(() => kutu.close(), 1200);
    } catch (hata) {
      durumSatiri.textContent = hata.message || "Bildirim gönderilemedi.";
    }
  });
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
