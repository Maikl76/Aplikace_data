# Portál sportovce a zákonného zástupce

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

Účet nejde založit jinak než z pozvánky: kdokoli jiný by se mohl
zaregistrovat „jako“ sportovec.

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
