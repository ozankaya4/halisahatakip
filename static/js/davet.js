/**
 * Davet jetonunu adresin # parçasından alıp forma koyar.
 *
 * NEDEN BÖYLE: jeton eskiden URL YOLUNDAYDI (/gruplar/katil/<jeton>/) ve o yol
 * hem nginx hem gunicorn erişim günlüğüne düz metin olarak yazılıyordu.
 * Veritabanı jetonun yalnızca SHA-256 özetini saklıyor — "veritabanı sızsa
 * bile çalışan bir davet bağlantısı üretilemesin" diye — ama günlükleri
 * okuyabilen biri çalışan bağlantıyı oradan alabiliyordu.
 *
 * Adresin # işaretinden sonraki parçası tarayıcıdan sunucuya HİÇ gitmez:
 * ne istek satırına, ne Referer başlığına, ne günlüğe girer. Jeton oradan
 * okunup POST gövdesine konuyor; gövde günlüklenmiyor.
 *
 * Betik yüklenmezse sayfa kullanıcıdan kodu elle yapıştırmasını istiyor.
 */

const form = document.querySelector("[data-davet-formu]");

if (form) {
  const alan = form.querySelector("[name=jeton]");
  const elleKutu = form.querySelector("[data-davet-elle]");
  const durum = form.querySelector("[data-davet-durum]");
  const dugmeler = form.querySelector("[data-davet-dugmeler]");

  // location.hash "#" ile başlıyor; baştaki işareti atıyoruz.
  const jeton = decodeURIComponent(window.location.hash.replace(/^#/, "")).trim();

  if (jeton) {
    alan.value = jeton;
    // Jeton adres çubuğunda kalmasın: kullanıcı sayfayı paylaşırsa ya da
    // ekran görüntüsü alırsa çalışan bir davet vermiş olmasın. Geçmişe yeni
    // kayıt eklemiyoruz, mevcut girdiyi değiştiriyoruz.
    history.replaceState(null, "", window.location.pathname);
    form.submit();
  } else {
    // Jeton yok: kullanıcı adresi eksik yapıştırmış olabilir. Elle giriş.
    if (durum) durum.textContent = "";
    if (elleKutu) elleKutu.hidden = false;
    if (dugmeler) dugmeler.hidden = false;
    alan?.focus();
  }
}
