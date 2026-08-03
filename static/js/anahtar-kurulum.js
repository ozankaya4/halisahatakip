/** Şifreleme parolası belirleme, kilit açma ve anahtar sıfırlama sayfası. */

import {
  anahtarPaketiHazirla,
  depoyuTemizle,
  ozelAnahtariAc,
  ozelAnahtariAl,
  webcryptoVarMi,
} from "./e2ee.js";
import { jsonIstek } from "./istek.js";

const kok = document.getElementById("anahtar-kurulum");
if (kok) kurulumuBaslat(kok);

function durumGoster(alan, metin, tur = "bilgi") {
  alan.textContent = metin;
  alan.dataset.tur = tur;
  alan.hidden = !metin;
}

async function kurulumuBaslat(kok) {
  const kullaniciId = kok.dataset.kullaniciId;
  const uyari = document.getElementById("ortam-uyarisi");

  if (!webcryptoVarMi()) {
    if (uyari) uyari.hidden = false;
    kok.querySelectorAll("form").forEach((f) => (f.hidden = true));
    return;
  }

  const olusturForm = document.getElementById("anahtar-olustur-formu");
  const acForm = document.getElementById("anahtar-ac-formu");
  const sifirlaForm = document.getElementById("anahtar-sifirla-formu");
  const kilitliRozet = document.getElementById("kilit-durumu");

  // Bu tarayıcıda anahtar açık mı?
  const acik = await ozelAnahtariAl(kullaniciId);
  if (acik && kilitliRozet) {
    kilitliRozet.textContent = "Bu tarayıcıda kilit açık";
    kilitliRozet.dataset.durum = "acik";
    if (acForm) acForm.hidden = true;
  }

  if (olusturForm) olusturmaBagla(olusturForm, kullaniciId);
  if (acForm) acmaBagla(acForm, kullaniciId);
  if (sifirlaForm) sifirlamaBagla(sifirlaForm);
}

function olusturmaBagla(form, kullaniciId) {
  const durum = form.querySelector(".islem-durumu");
  const dugme = form.querySelector("button[type=submit]");

  form.addEventListener("submit", async (olay) => {
    olay.preventDefault();
    const parola = form.querySelector("[name=parola]").value;
    const tekrar = form.querySelector("[name=parola_tekrar]").value;
    const enAz = Number(form.dataset.enAzUzunluk || 12);

    if (parola.length < enAz) {
      durumGoster(durum, `Parola en az ${enAz} karakter olmalı.`, "hata");
      return;
    }
    if (parola !== tekrar) {
      durumGoster(durum, "Parolalar birbirini tutmuyor.", "hata");
      return;
    }

    dugme.disabled = true;
    durumGoster(durum, "Anahtar üretiliyor, birkaç saniye sürebilir…", "bilgi");

    try {
      const { govde } = await anahtarPaketiHazirla(parola);
      await jsonIstek("/sohbet/api/anahtar/", { yontem: "POST", govde });

      // Hemen bu tarayıcıda da açalım ki kullanıcı ikinci kez parola girmesin.
      const kayit = await jsonIstek("/sohbet/api/anahtar/");
      await ozelAnahtariAc(kullaniciId, kayit, parola);

      durumGoster(durum, "Anahtarın hazır. Sohbete geçebilirsin.", "basari");
      setTimeout(() => window.location.reload(), 900);
    } catch (hata) {
      durumGoster(durum, hata.message, "hata");
      dugme.disabled = false;
    }
  });
}

function acmaBagla(form, kullaniciId) {
  const durum = form.querySelector(".islem-durumu");
  const dugme = form.querySelector("button[type=submit]");

  form.addEventListener("submit", async (olay) => {
    olay.preventDefault();
    const parola = form.querySelector("[name=parola]").value;

    dugme.disabled = true;
    durumGoster(durum, "Kilit açılıyor…", "bilgi");

    try {
      const kayit = await jsonIstek("/sohbet/api/anahtar/");
      if (!kayit.var) throw new Error("Henüz bir anahtarın yok.");
      await ozelAnahtariAc(kullaniciId, kayit, parola);
      durumGoster(durum, "Kilit açıldı.", "basari");
      setTimeout(() => window.location.reload(), 700);
    } catch (hata) {
      durumGoster(durum, hata.message, "hata");
      dugme.disabled = false;
    }
  });
}

function sifirlamaBagla(form) {
  const durum = form.querySelector(".islem-durumu");
  const onayKutusu = form.querySelector("[name=onay]");

  form.addEventListener("submit", async (olay) => {
    olay.preventDefault();
    if (!onayKutusu.checked) {
      durumGoster(durum, "Devam etmek için kutuyu işaretlemelisin.", "hata");
      return;
    }
    try {
      await jsonIstek("/sohbet/api/anahtar/sifirla/", { yontem: "POST" });
      await depoyuTemizle();
      durumGoster(durum, "Anahtarların silindi. Yeni parola belirleyebilirsin.", "basari");
      setTimeout(() => window.location.reload(), 900);
    } catch (hata) {
      durumGoster(durum, hata.message, "hata");
    }
  });
}
