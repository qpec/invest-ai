# Deep research: betrouwbare dekking van Scout-metrics

Datum: 2026-08-07

## Executive conclusion

De grootste winst komt niet uit één extra datavendor. De huidige meting mengt vier
verschillende problemen:

1. Het universum bevat veel buitenlandse secundaire noteringen, verouderde tickers,
   fondsen, trusts en zelfs beursgenoteerde obligaties.
2. SEC Company Facts bevat alleen niet-custom taxonomieën en feiten die voor de hele
   filing entity gelden. Dimensies en issuer extensions vallen daardoor weg.
3. De eigen allowlist en smalle tagchains laten veilige alternatieve US-GAAP-concepten
   liggen.
4. De lokale prijslaag ontbreekt volledig.

De aanbevolen volgorde is daarom:

1. security master en doeluniversum opschonen;
2. lokale EOD-prijzen plus corporate actions toevoegen;
3. veilige tagchain-uitbreidingen meten en valideren;
4. SEC Financial Statement Data Sets als tweede fundamentele bron toevoegen;
5. SEC Financial Statement and Notes en filing-instance Inline XBRL alleen gericht
   inzetten voor resterende gaten;
6. voor Nederlandse primaire noteringen ESEF/AFM toevoegen.

## Wat de lokale data daadwerkelijk laat zien

### Huidige dekking

- 7.486 regels in het samengestelde universum.
- 6.060 symbolen matchen direct met de SEC tickerkaart.
- 5.841 unieke Company Facts-payloads lokaal.
- 193 SEC Company Facts-requests eindigden in HTTP 404.
- 4.836 payloads leveren een point-in-time Scout-bundle op.
- 63.201 van 125.736 mogelijke metricwaarden zijn meetbaar, 50,3 procent.
- Geen enkel aandeel heeft alle 26 metrics, omdat de prijsafhankelijke
  `owner_fcf_yield_pct` overal ontbreekt.

### Het universum is vervuild

Van de 1.426 symbolen zonder SEC-match zijn er 1.359 als `United States` gelabeld en
slechts 67 als `Netherlands`. De niet-gematchte set bevat onder andere Frankfurt-,
Londen-, Berlijn-, Stuttgart-, Pink Sheet- en Kuala Lumpur-noteringen van Amerikaanse
bedrijven die ook een Amerikaanse primaire notering hebben. Voorbeelden zijn de
Londense regel voor MicroStrategy en Duitse regels voor Amerikaanse issuers.

De 193 HTTP 404's bestaan voor een groot deel uit closed-end funds, royalty trusts,
listed debt en andere instrumenten waarop de Scout-formules voor operationele bedrijven
niet passen. Voorbeelden zijn Nuveen- en BlackRock-fondsen en Entergy-obligaties.

Conclusie: een deel van het gemeten datagat is een identity- en eligibilityprobleem.
Meer fundamentals inkopen voor die regels verhoogt de datakwaliteit niet.

## Beperkingen van de huidige SEC-bron

De SEC documenteert dat Company Facts, Company Concept en Frames alleen feiten
aggregeren die:

- een niet-custom taxonomie gebruiken, zoals `us-gaap`, `ifrs-full`, `dei` of `srt`;
- gelden voor de hele filing entity.

Issuer extensions en dimensies vallen buiten deze API-selectie. Frames kiest bovendien
per issuer het laatst ingediende feit dat het best bij een kalenderperiode past. Dat is
handig voor cross-sectionele checks, maar ongeschikt als primaire bron voor issuers met
afwijkende boekjaren of exacte point-in-time-reconstructie.

Bron: SEC EDGAR API-documentatie:
https://www.sec.gov/search-filings/edgar-application-programming-interfaces

## Lokale tagprobe op ontbrekende metrics

Voor zes zwak gedekte metrics zijn telkens twaalf filers met een ontbrekende waarde
opnieuw als ongesnoeide Company Facts-payload onderzocht.

### Cash conversion

Bij de twaalf missende gevallen hadden er elf het concept `Depreciation`, tien
`AmortizationOfIntangibleAssets` en acht het reeds gebruikte gecombineerde
`DepreciationDepletionAndAmortization`.

De huidige chain accepteert alleen twee gecombineerde D&A-concepten. Een veilige
fallback kan `Depreciation + AmortizationOfIntangibleAssets` gebruiken wanneer het
gecombineerde concept voor exact dezelfde perioden ontbreekt. De implementatie moet
dubbel tellen blokkeren en financing-cost amortization uitsluiten.

### R&D intensity

Van twaalf missende gevallen hadden er drie het huidige
`ResearchAndDevelopmentExpense` en één het alternatieve
`ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost`.

Dit alternatief kan een kleine, verdedigbare lift geven. Andere hits waren tax credits,
deferred-tax assets en acquired in-process R&D. Die zijn semantisch ongeschikt als
operationele R&D-kosten. Afwezigheid mag daarom niet automatisch nul worden.

### Tax gap

Alle twaalf missende gevallen hadden zowel `IncomeTaxExpenseBenefit` als het huidige
pretax-incomeconcept; tien hadden ook `IncomeTaxesPaidNet`. Het gat zit hier vooral in
exacte periode-uitlijning en de eis dat income- en cashflowvensters samenvallen.

De beste verbetering is een exact-span matcher over jaarlijkse en kwartaalfeiten. Een
annual fallback is alleen toegestaan wanneer tax expense, pretax income en cash taxes
dezelfde start- en einddatum hebben. Losse TTM-benadering of vermenging van fiscale jaren
blijft verboden.

### Acquisition spend / OCF

Negen van twaalf missende gevallen hadden het al gebruikte
`PaymentsToAcquireBusinessesNetOfCashAcquired`; drie hadden daarnaast of in plaats
daarvan `PaymentsToAcquireBusinessesGross`.

Een gross-concept is een mogelijke tweede chain wanneer `net` ontbreekt. Het mag niet
worden gecombineerd met goodwill, stock consideration of pro-forma acquisition facts,
omdat die geen cash outflow voorstellen. Dat negen filers de huidige tag al hebben wijst
op window coverage als grotere oorzaak dan de tagchain.

### Owner FCF per-share growth

Alle twaalf missende gevallen hadden de gangbare diluted en basic weighted-average share
concepten. De sharechain is hier niet het primaire probleem. De ontbrekende historische
owner-FCF-reeks komt eerder door OCF, capex en exact aligned annual history.

### Incremental ROIC

Elf van twaalf missende gevallen hadden `OperatingIncomeLoss`, `StockholdersEquity`,
cash en long-term debt; alle twaalf hadden assets. De lage dekking komt vooral door de
vereiste vier aligned annual periods en de materialiteitsguards voor invested capital.

Die guards moeten blijven. Bij capital-light ondernemingen of krimpende/negatieve
invested capital is incremental ROIC geen betrouwbare ratio. Meer tags mogen de metric
alleen beschikbaar maken als dezelfde economische definitie over vier jaren kan worden
gereconstrueerd.

## Bronnen die daadwerkelijk extra informatie ontsluiten

### 1. SEC Financial Statement Data Sets

De compacte kwartaalsets bevatten numeric facts van de primaire financiële staten,
ongewijzigd `as filed`. De documentatie vermeldt zowel standaard- als custom tags.
Sinds de herverwerking van december 2024 gebruikt SEC rendering data om feiten op de
primaire staten te selecteren en bevat NUM een `segments`-veld.

Nut:

- custom tags die Company Facts uitsluit;
- primaire-statementfeiten met accession en filingcontext;
- betere reconstructie van OCF, capex, D&A, tax en invested-capitalcomponenten;
- batchgewijs lokaal te verwerken, zonder duizenden issuerrequests.

Beperking: update per kwartaal en geen volledige notes-dekking.

Bronnen:

- https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets
- https://www.sec.gov/files/financial-statement-data-sets.pdf

### 2. SEC Financial Statement and Notes Data Sets

Deze maandsets bevatten gedetailleerde numeric en text facts uit staten en toelichtingen,
inclusief dimensionele metadata. De SEC noemt ze expliciet veel uitgebreider dan de
compacte face-financial sets.

Nut:

- acquisition notes en cash consideration;
- tax notes en cash-taxdetails;
- dimensionele R&D- en D&A-feiten;
- issuer extensions;
- context voor conflictdetectie.

Beperking: bestanden zijn groot, vaak 70 tot 300 MB per maand en historische kwartalen
kunnen honderden MB groot zijn. Gebruik deze bron daarom als gerichte gap filler of
maandelijkse lokale batch, niet in iedere Scout-run.

Bronnen:

- https://www.sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets
- https://www.sec.gov/dera/data/fsnds.pdf

### 3. Inline XBRL filing packages

Inline XBRL bevat financiële staten, notes, schedules, context, units, dimensions en
issuer extensions in de originele filing. Een accession-gebaseerd archief is de hoogste
bewijslaag en kan amendments afzonderlijk bewaren.

Nut: maximale provenance en oplossing voor gevallen waarin batchsets conflicteren of
onvoldoende context bieden.

Beperking: hoogste engineering- en opslagkosten. Gebruik dit gericht voor de nieuwste
10-K/10-Q/20-F/40-F van filers die na de batchlagen nog een relevant gat hebben.

Bron: https://www.sec.gov/data-research/structured-data/inline-xbrl

### 4. SEC bulk archives en submissions

SEC publiceert `companyfacts.zip` en `submissions.zip` elke nacht rond 03:00 ET. De API
wordt realtime bijgewerkt. Bulkarchives zijn de expliciet aanbevolen route voor grote
hoeveelheden data.

Aanpak:

- nightly bulk snapshot voor volledige reconciliatie;
- submissions-delta voor nieuwe accessions en amendments;
- issuerrequests alleen voor urgente monitored names.

Bron: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

### 5. Nederlandse en Europese issuers

Voor de 67 echte Nederlandse primaire noteringen is ESEF de logische bron. AFM vermeldt
dat ESEF geldt voor boekjaren vanaf 2021 en jaarlijkse rapporten als XHTML/iXBRL worden
ingediend. XBRL International onderhoudt filings.xbrl.org als centrale ESEF-catalogus.

Bronnen:

- https://www.afm.nl/en/sector/effectenuitgevende-ondernemingen/financiele-en-duurzaamheidsverslaggeving/jaarlijkse-verslaggeving-in-esef
- https://filings.xbrl.org/docs/about
- https://www.xbrl.org/news/new-esef-filings-and-countries-available-catch-up-on-filings-xbrl-org/

## Prijslaag

### Directe winst

`owner_fcf_yield_pct` staat nu op 0 van 4.836 omdat er geen prijsgrid is. De fundamentele
bovengrens ligt tussen de circa 2.500 namen met owner FCF per share en 3.216 namen met
owner FCF in USD. Met geldige prijs, split history en frisse shares is een eerste dekking
van ongeveer 2.300 tot 3.000 namen plausibel. Dit is een te valideren bandbreedte, geen
garantie.

### Bronkeuze

- De repo ondersteunt Yahoo/yfinance al. Dat is geschikt voor een snelle coverage-
  baseline en een secundaire vergelijking, maar mist een contractuele data-SLA en sterke
  reproduceerbaarheid.
- Massive biedt Amerikaanse bars en expliciete splits/dividends, inclusief historische
  adjustment factors en point-in-time symbology. Dit past het best bij de Amerikaanse
  productieset.
- Tiingo biedt EOD-data plus aparte split- en dividendendpoints. Het is een redelijke
  tweede kandidaat voor US EOD.
- EODHD biedt wereldwijde EOD, raw en adjusted close, en bulk splits/dividends. Dit is
  aantrekkelijker wanneer Amsterdam en andere niet-US venues in dezelfde connector
  moeten vallen.

Bronnen:

- https://massive.com/docs/rest/stocks/corporate-actions/splits
- https://massive.com/docs/rest/stocks/corporate-actions/dividends
- https://www.tiingo.com/documentation/end-of-day
- https://www.tiingo.com/documentation/corporate-actions/splits
- https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends
- https://eodhd.com/financial-apis/api-for-historical-data-and-volumes

Aanbeveling: gebruik Yahoo direct voor de lokale baseline die de bestaande code al kan
produceren. Kies vóór productiekoppeling Massive voor US-only of EODHD voor US plus
Amsterdam. Bewaar altijd raw close, adjusted close, split events, dividend events,
security identifier, exchange, vendor timestamp en payload hash.

## Aanbevolen lokale architectuur

### Security master

Identiteit is leidend: `security_id`, CIK, LEI waar beschikbaar, ISIN/FIGI indien
gelicentieerd, primary exchange, ticker history, instrument type, active interval en
eligibility reason. Eén bedrijf kan meerdere securities hebben, maar Scout kiest één
toegelaten primaire ordinary-sharelijn.

### Evidence-lagen

1. `raw_artifact`: immutable payload/file, hash, URL, fetched_at en source vintage.
2. `filing`: CIK, accession, accepted_at, form, amendment link en report period.
3. `fact`: taxonomy, tag, unit, start/end, dimensions, value, decimals en accession.
4. `metric_observation`: formula version, value/status, as_of, calculated_at en exact
   gebruikte fact IDs.
5. `coverage_state`: `FRESH`, `STALE`, `MISSING`, `CONFLICT`, `NOT_APPLICABLE`,
   `INELIGIBLE_SECURITY` of `UNVERIFIABLE`, met reason code.

### Cronritme

- Dagelijks: security-master delta, EOD-prijzen en corporate actions.
- Na iedere handelsdag: alleen prijsafhankelijke metrics herberekenen.
- Nachtelijk: SEC submissions/companyfacts bulk delta en monitored-name fast path.
- Wekelijks: full-universe coverage reconciliation en retrybare failures.
- Maandelijks: SEC Financial Statement and Notes-set verwerken.
- Per kwartaal: compacte Financial Statement Data Set volledig reconciliëren.
- Eventgedreven: nieuwe 10-K/10-Q/20-F/40-F/accession parsen en betrokken metrics opnieuw
  berekenen.

## Prioriteit en verwachte richting

| Stap | Verwachte uitkomst | Risico |
|---|---|---|
| Security-master cleanup | Veel valse gaps verdwijnen uit de noemer; funds, debt en secondary listings worden expliciet uitgesloten | Entity resolution moet handmatig geaudit worden op uitzonderingen |
| Lokale prijslaag | Owner-FCF yield van 0 naar grofweg 2.300-3.000 bruikbare namen | Corporate actions en ticker history moeten correct zijn |
| Veilige D&A/tagchain patch | Materiële lift voor cash conversion | Dubbel tellen bij gecombineerd plus losse D&A |
| Exact-span tax/acquisition matcher | Lift voor tax gap en acquisitions/OCF zonder verschillende jaren te mengen | Coveragewinst mag windowdiscipline niet verzwakken |
| Compact SEC statement batches | Custom tags en segmentcontext op primaire staten | Kwartaalvertraging en as-filed inconsistenties |
| Notes-data gericht | Grootste resterende lift voor tax/acquisitions/R&D | Opslag, parsing en conflictresolutie |
| Inline XBRL last-mile | Hoogste bewijssterkte voor lastige filers | Hoogste engineeringkosten |
| ESEF voor NL | Betrouwbare fundamentele dekking voor echte Nederlandse primaries | IFRS mapping en issuer extensions |

## Wat unavailable moet blijven

- R&D bij afwezigheid van een operationeel R&D-expensefact.
- Tax gap wanneer tax expense, pretax income en cash taxes geen exact gelijk venster
  hebben.
- Acquisition cash spend wanneer alleen goodwill, consideration transferred of
  pro-formafeiten bestaan.
- Incremental ROIC bij onvoldoende aligned history, negatieve/noise-level invested
  capital of sectoren waarvoor de ratio economisch ongeschikt is.
- Owner FCF yield bij stale price, stale shares, ontbrekende corporate actions of
  onzekere security mapping.
- Alle 26 operationele metrics voor funds, listed debt, warrants en niet-operationele
  trusts wanneer de metricdefinitie niet past.

## Validatie-experiment

Voer de verbetering in vier meetbare rondes uit op een gestratificeerde gold set van 300
issuers en daarna op het volledige universum:

1. baseline Company Facts;
2. plus opgeschoonde identity en prijslaag;
3. plus veilige tagchains en compacte SEC statementsets;
4. plus notes/Inline XBRL voor resterende gaten.

Meet per ronde coverage, value agreement, point-in-time leakage, freshness, conflict rate
en volledige lineage. Direct gerapporteerde facts moeten op de gold set minimaal 99
procent exact overeenkomen met de filing. Een hogere coverage met lagere provenance of
stille imputatie geldt als regressie.
