# Knihovny pro prohlížeč

Jsou tady schválně, ne z CDN. Fakultní server může být za firewallem bez
přístupu do internetu a aplikace načítající skripty z CDN by se tam prostě
nespustila. Vedlejší efekt: funguje i offline a nezávisí na cizí službě.

| Soubor | Verze | Původ |
|---|---|---|
| `htmx.min.js` | 2.0.4 | npm `htmx.org` |
| `alpine.min.js` | 3.14.8 | npm `alpinejs` (dist/cdn.min.js) |
| `plotly-basic.min.js` | 2.35.2 | npm `plotly.js-basic-dist-min` |
| `tailwind.css` | 3.4.17 | sestaveno z šablon, viz níže |

## Plotly

Záměrně **basic** sestavení (1,1 MB místo 3,5 MB). Obsahuje scatter, bar
a pie – víc aplikace nepotřebuje. Kdyby přibyl typ grafu, který v basic
není (heatmap, box), vyměňte za `plotly.js-dist-min`.

## Tailwind

`tailwind.css` je sestavený výstup, ne runtime kompilátor. Obsahuje jen
třídy, které jsou v šablonách – proto má 10 kB. Po přidání nových tříd
do šablon je potřeba ho přegenerovat:

```bash
npx tailwindcss@3.4.17 \
    --content "templates/**/*.html" \
    -o static/vendor/tailwind.css --minify
```

Node je potřeba jen na tenhle krok, ne na provoz aplikace.

## Aktualizace

```bash
npm pack htmx.org@<verze> alpinejs@<verze> plotly.js-basic-dist-min@<verze>
```

a soubory z `dist/` zkopírovat sem. Nezapomeňte upravit verze v téhle tabulce.
