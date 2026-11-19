/*
  Individuální testování: výběr sportovce psaním příjmení, jména nebo kódu.

  Hledá se v prohlížeči v seznamu sportovců, který stránka dostala (jména jen
  ta, která účet smí vidět): bez ohledu na diakritiku a velikost písmen, slovo
  jména od začátku („nov“ najde Novákovou, i Svobodovou-Novákovou), kód kdekoli,
  sport, kategorie a tým od začátku slova; víc slov se musí shodovat všechna
  („nov ja“). Shoda v příjmení je první, pak abecedně podle příjmení. Vybraný
  sportovec se zapíše do skrytého pole „subject“ a HTMX překreslí údaje a testy.
*/

function bezDiakritiky(text) {
  return (text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function vyberSportovce(vychozi) {
  return {
    sportovci: [], vysledky: [], dalsi: 0, aktivni: -1, dotaz: "", vybrany: null,
    otevreno: false, chyba: "", limit: 30,

    init: function () {
      var self = this;
      var data = document.getElementById("sportovci-data");
      this.sportovci = data ? JSON.parse(data.textContent) : [];
      if (vychozi) {
        this.vybrany = this.sportovci.find(function (s) {
          return String(s.id) === String(vychozi);
        }) || null;
        if (this.vybrany) this.dotaz = this.vybrany.label;
      }
      if (!this.vybrany) {
        this.$nextTick(function () { self.$refs.vstup.focus({ preventScroll: true }); });
      }
      var form = this.$el.closest("form");
      if (form) {
        form.addEventListener("submit", function (e) {
          if (!self.$refs.hodnota.value) {
            e.preventDefault();
            self.chyba = "Vyberte sportovce – začněte psát jeho příjmení.";
            self.$refs.vstup.focus();
          }
        });
      }
    },

    hledat: function () {
      // Kdo po výběru přepíše text, výběr ruší (a údaje o sportovci zmizí).
      if (this.vybrany && this.dotaz !== this.vybrany.label) {
        this.vybrany = null;
        this.nastavit("");
      }
      var slova = bezDiakritiky(this.dotaz).split(/\s+/).filter(Boolean);
      var nalez = [];
      this.sportovci.forEach(function (s) {
        var poradi = 0;
        for (var i = 0; i < slova.length; i++) {
          var t = slova[i];
          var vJmenu = s.jmeno.some(function (w) { return w.indexOf(t) === 0; });
          var vKodu = s.kod.indexOf(t) !== -1;
          var jinde = s.ostatni.some(function (w) { return w.indexOf(t) === 0; });
          if (!vJmenu && !vKodu && !jinde) return;
          var vPrijmeni = s.prijmeni.some(function (w) { return w.indexOf(t) === 0; });
          if (i === 0) poradi = vPrijmeni ? 0 : vJmenu ? 1 : vKodu ? 2 : 3;
        }
        nalez.push([poradi, s]);
      });
      nalez.sort(function (a, b) {
        return a[0] - b[0] || a[1].label.localeCompare(b[1].label, "cs");
      });
      this.dalsi = Math.max(0, nalez.length - this.limit);
      this.vysledky = nalez.slice(0, this.limit).map(function (x) { return x[1]; });
      this.aktivni = this.vysledky.length ? 0 : -1;
      this.otevreno = true;
    },

    posunout: function (krok) {
      if (!this.otevreno) { this.hledat(); return; }
      if (!this.vysledky.length) return;
      this.aktivni = (this.aktivni + krok + this.vysledky.length) % this.vysledky.length;
      var el = document.getElementById("sportovec-" + this.vysledky[this.aktivni].id);
      if (el) el.scrollIntoView({ block: "nearest" });
    },

    potvrdit: function () {
      if (this.otevreno && this.aktivni >= 0) this.vybrat(this.vysledky[this.aktivni]);
    },

    vybrat: function (s) {
      this.vybrany = s;
      this.dotaz = s.label;
      this.otevreno = false;
      this.chyba = "";
      this.nastavit(s.id);
    },

    zrusit: function () {
      this.vybrany = null;
      this.dotaz = "";
      this.nastavit("");
      this.$refs.vstup.focus();
      this.hledat();
    },

    nastavit: function (id) {
      var pole = this.$refs.hodnota;
      if (String(pole.value) === String(id)) return;
      pole.value = id;
      if (window.htmx) window.htmx.trigger(pole, "vybran");
    }
  };
}
