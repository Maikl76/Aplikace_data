/*
  Vykreslení grafů. Figury sestavuje Python a sem přijdou jako JSON;
  plotly.js je jen nakreslí. Když má graf i tmavou variantu, vybere se
  podle režimu a při přepnutí režimu se graf překreslí.
*/
(function () {
  function vykreslit() {
    var dark = document.documentElement.classList.contains("dark");
    document.querySelectorAll(".js-graf").forEach(function (wrap) {
      var id = wrap.dataset.target;
      var zdroj = (dark && document.getElementById(id + "-data-dark")) ||
                  document.getElementById(id + "-data");
      if (!zdroj || !window.Plotly) return;
      var data = JSON.parse(zdroj.textContent);
      // Na úzkém displeji (telefon) zúžit okraj pro popisky a zmenšit písmo,
      // jinak by na samotný graf nezbylo místo.
      if (wrap.clientWidth < 520 && data.layout.margin && data.layout.margin.l > 90) {
        data.layout.margin.l = 90;
        data.layout.yaxis = Object.assign({}, data.layout.yaxis, { tickfont: { size: 9 } });
      }
      Plotly.react(id, data.data, data.layout, {
        displayModeBar: false, responsive: true, locale: "cs",
      });
    });
  }
  document.addEventListener("DOMContentLoaded", vykreslit);
  document.addEventListener("rezim", vykreslit);
})();
