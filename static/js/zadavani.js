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
