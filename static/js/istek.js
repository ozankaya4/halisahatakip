/** Küçük fetch sarmalayıcı — CSRF jetonunu otomatik ekler. */

function cerezOku(ad) {
  const parcalar = document.cookie ? document.cookie.split(";") : [];
  for (const parca of parcalar) {
    const temiz = parca.trim();
    if (temiz.startsWith(ad + "=")) {
      return decodeURIComponent(temiz.slice(ad.length + 1));
    }
  }
  return null;
}

export function csrfJetonu() {
  return cerezOku("hst_csrftoken") || "";
}

export async function jsonIstek(url, { yontem = "GET", govde = null } = {}) {
  const secenekler = {
    method: yontem,
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  };

  if (govde !== null) {
    secenekler.headers["Content-Type"] = "application/json";
    secenekler.body = JSON.stringify(govde);
  }
  if (yontem !== "GET") {
    secenekler.headers["X-CSRFToken"] = csrfJetonu();
  }

  const yanit = await fetch(url, secenekler);
  let veri = null;
  try {
    veri = await yanit.json();
  } catch {
    throw new Error(`Sunucu beklenmedik bir yanıt döndü (${yanit.status}).`);
  }

  if (!yanit.ok || veri.tamam === false) {
    const hata = new Error(veri.hata || `İstek başarısız (${yanit.status}).`);
    hata.durum = yanit.status;
    throw hata;
  }
  return veri;
}
