/*
  Zadávání u přístroje: stopky a odpočet pauzy mezi pokusy.
  Obojí běží jen v prohlížeči, nic neposílá na server.
*/

function formatCas(ms, desetin) {
  var s = ms / 1000;
  var min = Math.floor(s / 60);
  var sec = s - min * 60;
  var text = sec.toFixed(desetin);
  if (min > 0 && sec < 10) text = "0" + text;
  return (min > 0 ? min + ":" + text : text).replace(".", ",");
}

function stopky() {
  return {
    open: false, bezi: false, zacatek: 0, ubehlo: 0, casovac: null, pole: null, des: 2,
    otevrit: function (detail) {
      this.pole = detail.pole; this.des = detail.des; this.vynulovat(); this.open = true;
    },
    prepnout: function () {
      var self = this;
      if (this.bezi) {
        clearInterval(this.casovac);
        this.ubehlo = performance.now() - this.zacatek;
        this.bezi = false;
      } else {
        this.zacatek = performance.now() - this.ubehlo;
        this.bezi = true;
        this.casovac = setInterval(function () { self.ubehlo = performance.now() - self.zacatek; }, 31);
      }
    },
    mezernik: function (e) {
      // Mezerník ovládá stopky jen když jsou otevřené – jinak se píše normálně.
      if (!this.open) return;
      e.preventDefault();
      this.prepnout();
    },
    vynulovat: function () { clearInterval(this.casovac); this.bezi = false; this.ubehlo = 0; },
    get text() { return formatCas(this.ubehlo, 2); },
    get vysledek() { return (this.ubehlo / 1000).toFixed(this.des).replace(".", ","); },
    zapsat: function () {
      if (this.pole) {
        this.pole.value = this.vysledek;
        this.pole.dispatchEvent(new Event("input", { bubbles: true }));
      }
      this.open = false;
    },
  };
}

function pauza() {
  return {
    bezi: false, hotovo: false, celkem: 0, konec: 0, zbyva: 0, casovac: null,
    spustit: function (sekundy) {
      var self = this;
      clearInterval(this.casovac);
      this.celkem = sekundy * 1000; this.konec = Date.now() + this.celkem;
      this.zbyva = this.celkem; this.bezi = true; this.hotovo = false;
      this.casovac = setInterval(function () {
        self.zbyva = Math.max(0, self.konec - Date.now());
        if (self.zbyva === 0) { clearInterval(self.casovac); self.bezi = false; self.hotovo = true; self.signal(); }
      }, 200);
    },
    zastavit: function () { clearInterval(this.casovac); this.bezi = false; this.hotovo = false; },
    get text() {
      var s = Math.ceil(this.zbyva / 1000);
      return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    },
    get procenta() { return this.celkem ? 100 - this.zbyva / this.celkem * 100 : 0; },
    signal: function () {
      try { navigator.vibrate && navigator.vibrate([300, 150, 300]); } catch (e) {}
      try {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        [0, 0.35].forEach(function (t) {
          var osc = ctx.createOscillator(), gain = ctx.createGain();
          osc.frequency.value = 880; osc.connect(gain); gain.connect(ctx.destination);
          gain.gain.setValueAtTime(0.25, ctx.currentTime + t);
          osc.start(ctx.currentTime + t); osc.stop(ctx.currentTime + t + 0.25);
        });
      } catch (e) {}
    },
  };
}

/*
  Kontrola hned při zadávání: rozptyl pokusů a věrohodný rozsah se počítají
  v prohlížeči z toho, co je v políčkách – stejnými slovy, jaká pak napíše
  server po uložení. Sportovec ještě stojí na desce, pokus jde změřit znovu.
*/
function parseCislo(raw) {
  var text = String(raw || "").trim().replace(",", ".").replace(/\s/g, "");
  if (!text) return null;
  if (text.indexOf(":") >= 0) {
    var parts = text.split(":");
    var min = parseInt(parts[0], 10), sec = parseFloat(parts[1]);
    if (isNaN(min) || isNaN(sec) || sec >= 60) return null;
    return Math.abs(min) * 60 + sec;
  }
  var v = parseFloat(text);
  return isNaN(v) ? null : v;
}

function cz0(v) { return Math.round(v).toString(); }

function kontrolaRadku(tr) {
  var box = tr.querySelector("[data-kontrola]");
  if (!box) return;
  var limit = parseFloat(tr.dataset.cvLimit);
  var min = tr.dataset.min === "" ? null : parseFloat(tr.dataset.min);
  var max = tr.dataset.max === "" ? null : parseFloat(tr.dataset.max);
  var unit = tr.dataset.unit ? " " + tr.dataset.unit : "";
  var values = [], outside = [];
  tr.querySelectorAll("input.js-hodnota").forEach(function (inp) {
    var n = parseInt(inp.dataset.pokus, 10);
    var v = parseCislo(inp.value);
    if (v === null) return;
    var neplatny = document.querySelector('input[name="neplatny|' + n + '"]');
    if (!(neplatny && neplatny.checked)) values.push([n, v]);
    if ((min !== null && v < min) || (max !== null && v > max)) outside.push(n);
  });
  var texts = [];
  if (!isNaN(limit) && values.length >= 2) {
    var mean = values.reduce(function (a, p) { return a + p[1]; }, 0) / values.length;
    if (mean !== 0) {
      var variance = values.reduce(function (a, p) { return a + Math.pow(p[1] - mean, 2); }, 0) / (values.length - 1);
      var cv = Math.abs(Math.sqrt(variance) / mean * 100);
      if (cv > limit) {
        var worst = null;
        values.forEach(function (p) {
          var others = values.filter(function (q) { return q[0] !== p[0]; });
          var m = others.reduce(function (a, q) { return a + q[1]; }, 0) / others.length;
          if (!m) return;
          var dev = Math.abs(p[1] - m) / Math.abs(m) * 100;
          if (!worst || dev > worst[1]) worst = [p[0], dev];
        });
        var text = "Pokusy se liší o " + cz0(cv) + " % (mez " + limit + " %)";
        texts.push(worst ? text + ": pokus " + worst[0] + " se liší o " + cz0(worst[1]) + " % od ostatních – změřit znovu?" : text + " – změřit znovu?");
      }
    }
  }
  if (outside.length) {
    var span = (min !== null && max !== null) ? min + "–" + max + unit : (min !== null ? "od " + min + unit : "do " + max + unit);
    texts.push((outside.length === 1 ? "Pokus " : "Pokusy ") + outside.join(", ") + " mimo věrohodný rozsah (" + span + ") – překlep, nebo chyba přístroje?");
  }
  box.innerHTML = texts.map(function (t) { return "<div>⚠ " + t + "</div>"; }).join("");
}

document.addEventListener("input", function (e) {
  if (e.target.classList && e.target.classList.contains("js-hodnota")) kontrolaRadku(e.target.closest("tr"));
});
document.addEventListener("change", function (e) {
  // Označení neplatného pokusu mění, co se počítá – přepočítat všechny řádky.
  if (e.target.name && e.target.name.indexOf("neplatny|") === 0)
    document.querySelectorAll("tr[data-kontrola], tr").forEach(function (tr) { if (tr.querySelector("[data-kontrola]")) kontrolaRadku(tr); });
});
// Enter = další políčko: číselná klávesnice tabletu nemá tabulátor.
document.addEventListener("keydown", function (e) {
  if (e.key !== "Enter" || !e.target.classList || !e.target.classList.contains("js-hodnota")) return;
  e.preventDefault();
  var all = Array.prototype.slice.call(document.querySelectorAll("input.js-hodnota"));
  var i = all.indexOf(e.target);
  if (i >= 0 && i + 1 < all.length) { all[i + 1].focus(); all[i + 1].select && all[i + 1].select(); }
});
