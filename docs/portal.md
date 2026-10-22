# Portál sportovce, zákonného zástupce a trenéra

Sportovec je subjektem údajů: má nárok vidět všechno o sobě, včetně toho,
kdo si jeho data zobrazil. Portál (`/muj/`) mu dává vlastní výsledky,
trendy, vydané zprávy pro sportovce, dotazník k dnešnímu měření, souhlasy
a sdílení s trenérem. Laboratoř v portálu nic nezadává.

## Jak sportovec získá účet

1. Laboratoř na kartě sportovce (**Účet a sdílení s trenérem**) vystaví
   **pozvánku** – pro sportovce, nebo pro zákonného zástupce nezletilého.
2. Pozvánka je odkaz s QR kódem; platí 30 dní a jde použít jednou. Předává
   se osobně (vytištěná, naskenovaná z obrazovky) nebo e‑mailem, pokud má
   sportovec uložený kontakt a server umí posílat e‑maily (`EMAIL_HOST`).
3. Sportovec odkaz otevře, zadá e‑mail a heslo (aspoň 12 znaků) a účet je
   hotový. Rodič s účtem otevře pozvánku pro druhé dítě přihlášený – dítě
   se k účtu připojí.

Další dvě cesty, obě přes e‑mail (server musí umět posílat poštu,
`EMAIL_HOST`):

- **Po schválení objednávky** odejde pozvánka automaticky v potvrzení
  objednávky – dospělému pro sportovce, nezletilému pro zákonného zástupce.
  Nevyužitá pozvánka je vidět i na kartě sportovce.
- **Přihlášení e‑mailem** (odkaz na přihlašovací stránce): sportovec nebo
  rodič zadá e‑mail, který má laboratoř uložený. Má‑li už účet, přijde
  odkaz pro přihlášení (platí 30 minut); jinak pozvánka k založení účtu.
  Odpověď stránky je vždy stejná, takže nejde zkoušet, které adresy
  laboratoř zná; z jedné adresy jde poslat nejvýš pět žádostí za hodinu.

Bez e‑mailu zůstává jen pozvánka: kdokoli jiný by se mohl zaregistrovat
„jako“ sportovec.

## Sdílení s trenérem

Tým v aplikaci je organizační skupina laboratoře, ne právní titul k datům.
Trenér vidí sportovce jen po dobu **aktivního sdílení**, jinak ani pod
kódem.

- Sdílení **potvrzuje sportovec nebo zákonný zástupce ve svém účtu**
  (Souhlasy a sdílení). Laboratoř i trenér o něj mohou jen požádat; žádost
  se sportovci ukáže k rozhodnutí.
- Sportovec si sdílení může zapnout i sám, výběrem trenéra ze seznamu.
- Potvrzením vzniká souhlas „Sdílení výsledků s trenérem“, odvolat ho jde
  kdykoli jedním tlačítkem; trenér od té chvíle nevidí nic.
- Při anonymizaci sportovce se sdílení odvolá a účty bez sportovce se vypnou.

## Co sportovec vidí

- klíčové ukazatele s posouzením proti pásmu chyby měření, trendy,
  seznam měření,
- vydané zprávy **pro sportovce** (zprávy pro trenéra a lékaře ne),
- dotazník RPE k dnešnímu měření (stejný formulář jako přes QR kód),
- souhlasy, které laboratoř eviduje,
- **kdo se díval**: posledních 40 záznamů auditu k jeho datům.

Účty portálu nemají přístup do obrazovek laboratoře ani do administrace;
každý pokus je přesměruje zpět do portálu.

## Portál trenéra

Účet trenéra zakládá správce v administraci (role Trenér, jméno
a příjmení). Trenér v portálu (`/trener/`) vidí:

- jen sportovce, kteří mu sdílení potvrdili – jménem, s klíčovými
  ukazateli, trendy, stranovými rozdíly a seznamem měření,
- přehled skupiny po bateriích testů (poslední hodnota, změna proti minule
  nad pásmem chyby měření, průměr skupiny),
- vydané zprávy **pro trenéra**; zprávy pro sportovce a lékaře ne.

O sdílení žádá **kódem sportovce** (sportovec ho má na QR kartě a ve svém
účtu). Dokud sportovec žádost nepotvrdí, trenér nevidí nic, ani jméno.
Každé zobrazení se zapisuje do auditu a sportovec ho vidí v „Kdo se díval“.
