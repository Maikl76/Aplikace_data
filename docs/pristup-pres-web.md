# Přístup přes web a nasazení: otevřené rozhodnutí

Poznámka z diskuse (listopad 2026), ke které se vrátíme, až bude vyřešen
přenos nastavení mezi instancemi. Zadání: aplikace běží lokálně na více
počítačích v laboratoři; metodici mají doplňovat články ze svých
počítačů a správce má spravovat aplikaci i jinak než jen lokálně.

## Východisko

Aplikace je serverová: běží na jednom místě a používá se v prohlížeči.
Kopie na každém počítači s přenosem katalogu je provizorium z doby bez
serveru. Jakmile poběží jedna instance v síti, metodik článek doplní
tím, že si otevře prohlížeč. Otázka tedy zní, kde ta jedna instance
poběží a odkud bude dostupná.

## Čtyři cesty

| Cesta | Co to znamená | Pro koho | Co je třeba |
|---|---|---|---|
| **A. Fakultní server a VPN UK** (cíl) | VM od IT v síti fakulty, adresa typu `diagnostika.ftvs.cuni.cz`, certifikát od IT. V budově přístup rovnou, z domova přes VPN univerzity. | všichni zaměstnanci | nic v aplikaci; balíček v `deploy/` a `docs/offline-server.md` už existují; IT: VM, adresa, certifikát, porty 443, SSH |
| **B. Laboratorní počítač jako server** (mezikrok) | Jediná instance na jednom PC v síťovém režimu (`spustit-sit.bat`), ostatní PC a tablety v prohlížeči. Jediná databáze v laboratoři. | laboratoř, pracovny jen ve stejné síti | stabilnější spuštění jako služba Windows místo vývojového serveru, PC stále zapnuté |
| **C. Instance s daty přímo na internetu** | Bez VPN. Technicky možné (HTTPS, zámek po neúspěšných přihlášeních). | kdokoli s účtem | dvoufaktorové přihlášení (zatím není), omezení na adresy fakulty na firewallu, souhlas fakulty a pověřence |
| **D. Oddělit znalostní a provozní část** | Veřejná instance (PythonAnywhere) jen se znalostmi: články, karty, normy, pravidla, texty. Žádní sportovci. Server si znalosti stahuje. | metodici bez VPN, externisté | přenos nastavení mezi instancemi (dávka 14), pravidlo „znalosti se upravují jen na jednom místě“ |

## Doporučení

Cíl je A. Hned začít B, aby v laboratoři byla jedna databáze. D přidat,
jen když mezi metodiky budou lidé bez účtu UK, nebo když se server od IT
protáhne. C jen s dvoufaktorem a souhlasem fakulty.

Správa na dálku: většina je už ve webu (Kolegové a přístupy, Nastavení,
Provoz a zálohy, katalog, model). Mimo prohlížeč zůstává aktualizace
verze (SSH přes VPN, nebo tlačítko v Provozu, které by na serveru
stáhlo vydanou verzi a restartovalo – zvážit až na fakultním serveru se
zálohou před každou aktualizací), obnova ze zálohy a změna klíčů v `.env`.

Data sportovců (zdravotní a genetické údaje) zůstávají na fakultě.
Veřejná instance nikdy nenese skutečná data.

## Otázky k rozhodnutí

1. Je fakultní server od IT v dohledu, nebo počítat s laboratorním PC déle?
2. Mají všichni metodici účet UK (VPN)? Jsou mezi nimi externisté?
3. Co přesně chce správce dělat na dálku: účty a přístupy, nastavení,
   aktualizace, zálohy?
4. Má veřejná instance zůstat ukázkou, nebo se stát znalostní instancí (D)?

Podle odpovědí: žádost pro IT s požadavky na server, spouštění
laboratorního PC jako služby, dvoufaktorové přihlášení, nebo automatická
synchronizace znalostí mezi instancemi.
