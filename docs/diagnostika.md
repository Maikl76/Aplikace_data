# Diagnostické ukazatele

## Dynamic Strength Index (DSI)

**DSI = koncentrická vrcholová síla v CMJ ÷ vrcholová síla v IMTP** téhož
dne (hodnoty dne = průměr platných pokusů hlavního měření). Aplikace ho
dopočítá sama po importu nebo ručním zadání; u starších dat stačí spustit
`spustit.bat` (nebo `python manage.py prepocitat_odvozene`).

Orientační výklad z literatury: **pod 0,60** sportovec v dynamickém pohybu
využije jen menší část své maximální síly → prostor pro balistický
a rychlostně-silový trénink; **nad 0,80** velkou část → prostor pro rozvoj
maximální síly. DSI neříká, jak byl skok proveden – čtěte ho spolu se
strategií CMJ (níže).

Pravidla `dsi_nizky` a `dsi_vysoky` jsou v katalogu **vypnutá** a články
k nim **navržené**. Až prahy a literaturu odsouhlasíte, zapněte pravidla
a schvalte články (Katalog → Pravidla, Katalog → Články).

MDC pro DSI zatím není vyplněná. Thomas a kol. (2015) uvádějí typickou
chybu 0,03, tj. MDC ≈ 0,08 – ale na univerzitních sportovcích a z jiného
typu skoku; nejlepší je vlastní reliabilita laboratoře.

Literatura (návrhy v katalogu):
- McMahon JJ a kol. (2017), Sports 5(4):72, doi:10.3390/sports5040072
- Comfort P a kol. (2018), Sports 6(4):176, doi:10.3390/sports6040176
- Comfort P a kol. (2018), IJSPP 13(3):320–325, doi:10.1123/ijspp.2017-0255
- Thomas C a kol. (2015), IJSPP 10(5):542–545, doi:10.1123/ijspp.2014-0255

## CMJ podle ODS (výsledek – příčina – strategie)

Ukazatele skoku jsou rozdělené podle toho, co znamenají:

| Role | Ukazatele | Otázka |
|---|---|---|
| **Výsledek** | výška výskoku, RSI-modified | co sportovec dokázal |
| **Příčina** | koncentrická vrcholová síla, výkon / hmotnost, excentrické brzdné RFD | co výsledek pohání |
| **Strategie** | hloubka protipohybu, doba kontrakce | jak skok provedl |

Zpráva u CMJ ukáže tři sloupce a jednu větu výkladu, např. „Skutečná
změna výsledku (výška výskoku). Změnila se i strategie skoku: hloubka
protipohybu.“ Výklad se opírá **jen o změny nad MDC** – u metrik bez MDC
se nic netvrdí. Roli lze změnit u metriky v katalogu (pole „role v ODS“).

## Rozptyl pokusů

U metrik s vyplněnou mezí („max. rozptyl pokusů (CV %)“, výchozí 10 %
u výšky výskoku, RSI, sil v CMJ a IMTP) aplikace hlídá, jestli se pokusy
téhož dne neliší víc, než je obvyklé:

- v **náhledu importu** (sportovec je často ještě v laboratoři),
- na **testovacím dni**,
- ve **zprávě** u dané hodnoty („rozptyl pokusů 11,8 % ▲“).

Mez je výchozí nastavení laboratoře, ne norma – upravte ji podle zkušenosti.
