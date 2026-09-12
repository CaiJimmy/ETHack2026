"""Hand-verified parent-string to ticker overrides for the entity-resolution lane.

Keys are raw-ish parent strings as EPA writes them; match_parents.py normalises them with the
same key function it applies to the data, so spelling of punctuation and legal suffixes here
does not matter. Every entry is a corporate action or a subsidiary that automated matching
cannot see, and each carries the evidence used to accept it.

Weighted by tonnes, not by rows: an entry earns its place by how much measured CO2e it moves.
"""

# Parent string -> S&P 500 ticker. Ordered roughly by the emissions each entry carries.
OVERRIDES = {
    # Power generation
    "CPN MANAGEMENT LP": "CEG",  # Calpine's filing entity, 44 facilities / 47.7 MMT in RY2023; Violation Tracker files calpine-* subsidiaries under the parent page that declares ticker CEG
    "CALPINE CORP": "CEG",  # same fleet, the spelling EPA used before 2017
    "VOLT PARENT LP": "CEG",  # Calpine's post-LBO holdco (Energy Capital Partners vehicle), same facility ids in adjacent years
    "DYNEGY INC": "VST",  # Vistra acquired Dynegy in April 2018; EPA still files the legacy name through RY2023
    "OAK GROVE MANAGEMENT COMPANY LLC": "VST",  # Oak Grove lignite station, Robertson County TX, operated by Vistra's Luminant
    "PACIFICORP": "BRK.B",  # Berkshire Hathaway Energy utility; Violation Tracker carries 'pacificorp energy' under BRK.B but not the bare name
    "MONONGAHELA POWER COMPANY": "FE",  # FirstEnergy's West Virginia utility (Fort Martin, Harrison, Pleasants)
    "SCANA CORP": "D",  # Dominion Energy acquired SCANA in January 2019
    "SOUTH CAROLINA ELECTRIC & GAS CO": "D",  # SCANA's operating utility, renamed Dominion Energy South Carolina
    "PPL GENERATION LLC": "PPL",  # PPL's own generation subsidiary, 2010-2014
    "INTEGRYS ENERGY GROUP INC": "WEC",  # WEC Energy Group acquired Integrys in June 2015; overrides a Violation Tracker alias that points at EXC because Exelon bought only the retail arm. The four facilities are Wisconsin plants (Columbia, Riverside)
    "SEMPRA ENERGY": "SRE",  # EPA's spelling with the ENERGY suffix; the index name is the bare "Sempra", which keys differently
    "NV ENERGY": "BRK.B",  # EPA names BERKSHIRE HATHAWAY INC as the parent of the same seven ORIS plants CAMD files under NV Energy (Lenzie, Higgins, Silverhawk, Clark, Harry Allen, Sun Peak, Las Vegas)
    "LA FRONTERA HOLDINGS LLC": "VST",  # EPA names Vistra Corp 100% owner of the Forney, Lamar and Odessa-Ector facilities that CAMD files under La Frontera
    "MIAMI FORT POWER COMPANY LLC": "VST",  # EPA names Vistra Corp 100% owner of the Miami Fort Generating Station
    "GREAT PLAINS ENERGY INC": "EVRG",  # merged with Westar in 2018 to form Evergy

    # Oil, gas and refining
    "VALERO CORP": "VLO",  # EPA's short spelling 2010-2015, same refinery ids as VALERO ENERGY CORP
    "TESORO CORP": "MPC",  # Tesoro renamed Andeavor in 2017 and Marathon Petroleum acquired it in October 2018
    "ANDEAVOR": "MPC",  # same company, the name EPA used in 2017-2018
    "MARATHON OIL COMPANY": "COP",  # ConocoPhillips completed the Marathon Oil acquisition in November 2024
    "HESS CORP": "CVX",  # Chevron completed the Hess acquisition in July 2024
    "PIONEER NATURAL RESOURCES CO": "XOM",  # ExxonMobil completed the Pioneer acquisition in May 2024
    "MPLX LP": "MPC",  # Marathon Petroleum consolidates MPLX in its financial statements, so the denominator this feeds is consolidated too; Violation Tracker files MPLX's operating company Marathon Pipe Line under MPC
    "DENBURY INC": "XOM",  # ExxonMobil acquired Denbury in November 2023

    # Materials and industrials
    "WESTROCK CO": "SW",  # WestRock combined with Smurfit Kappa in July 2024 to form Smurfit Westrock plc
    "DUPONT DE NEMOURS INC": "DD",  # the specialty business that kept the DuPont name after the 2019 three-way split
}

# Parent strings that automated matching claims for a ticker but that are a different company.
# Blocked before every other route, with the evidence that they are not the same entity.
BLOCKED = {
    "OHIO POWER PARTNERS LLC": "Middletown Energy Center, a merchant gas plant built by NTE Energy, not AEP's Ohio Power Company; the name collides only after PARTNERS is stripped",
    "MORNINGSTAR PARTNERS LP": "oil and gas producer, unrelated to Morningstar Inc; the GHGRP lane flagged the same key collision",
    "TITAN AMERICA LLC": "cement producer, not Titan International; neither is an S&P 500 member",
    "THE MORNING STAR CO": "California tomato processor; collides with Morningstar Inc (MORN) once THE and CO are stripped",
    "CORNING ENERGY CORP": "Corning Natural Gas Corporation of New York, not Corning Inc (GLW)",
    "CENTERPOINT HOLDINGS LLC": "CenterPoint Landfill in Oklahoma, NAICS 562212, not CenterPoint Energy",
    "THE KRAFT GROUP": "Rand-Whitney Containerboard, the Kraft family's packaging business, not Kraft Foods",
    "THE INTERNATIONAL GROUP INC": "wax and petrolatum refiner, not International Paper",
    "MARATHON": "the bare name does not distinguish Marathon Petroleum from Marathon Oil",
    "ENERGY HARBOR CORP": "Vistra bought Energy Harbor's nuclear and retail business in March 2024 and explicitly did not buy the coal fleet. The only two facilities EPA files under this name are W H Sammis and Pleasants Power Station, both already sold to third parties before the deal, so sending this string to VST added 13.75 MMT to Vistra's 2022 history that Vistra never owned",
    "E I DU PONT DE NEMOURS & CO": "legacy DuPont. Four fifths of the 12.8 MMT this string carries in 2014 sits at plants that went to Chemours in the 2015 spin (Louisville Works 6.0 MMT, Washington Works, Chambers Works, DeLisle, Fayetteville, Johnsonville) and most of the rest is Sabine River Works, which went to Dow. DuPont de Nemours (DD) owns almost none of it, so the string is left unmatched and DD carries only the sites EPA files under DUPONT DE NEMOURS INC",
    "WASTE INDUSTRIES USA INC": "Raleigh waste hauler bought by GFL Environmental in 2018, not Waste Management. It collided with WM's SEC former name USA WASTE SERVICES INC because the strict key strips INDUSTRIES, USA and SERVICES and leaves both sides as WASTE. The two facilities are W I Taylor County Landfill (GA) and Lakeway Sanitation (TN)",
}

# Managers whose named ownership of an emitting facility is a fund holding, not consolidation.
# A carbon price lands on the portfolio company's income statement, not the manager's, so these
# tickers are excluded from every automatic route, including a direct name match: EPA names
# ARES MANAGEMENT CORP as the parent of 1.45 MMT of RY2023 emissions, which would otherwise
# swamp a company whose own operations emit almost nothing. Those tonnes are reported as
# unattributed instead. Berkshire is deliberately NOT on this list: Berkshire Hathaway Energy
# is a consolidated subsidiary in its 10-K.
# Checked one by one against the facilities EPA files under each name: every last one is a
# fund or portfolio asset, not the manager's own operations.
FUND_OWNER_TICKERS = {
    "ARES",  # St. Joseph Energy Center, a 1.45 MMT gas plant in Indiana
    "BLK",   # Hardee Power Station, Florida
    "GS",    # JW Aluminum, South Carolina
    "KKR",   # Fort Lupton and Keenesburg gas plants, Colorado; Lea Power Partners, New Mexico
    "JPM",   # El Paso Electric, held by IIF, a JPMorgan-managed infrastructure fund
    "BX",    # JW Aluminum before it passed to Goldman
    "MS",    # Durango Midstream, in Morgan Stanley Infrastructure Partners
    "WFC",   # PennEnergy Resources, Appalachian gas
    "APO",   # US Silica
    "BAC",
    "C",
}

# Why the largest unmatched emitters are unmatched. Used to categorise
# unmatched_top_emitters.csv, which is the honesty slide and the worklist.
UNMATCHED_NOTES = {
    "US GOVERNMENT": "federal (Tennessee Valley Authority)",
    "CPS ENERGY": "municipal (City of San Antonio)",
    "SALT RIVER PROJECT": "public power district (Arizona)",
    "SALT RIVER PROJECT AGRICULTURAL IMPROVEMENT & POWER DISTRICT": "public power district (Arizona)",
    "SOUTH CAROLINA PUBLIC SERVICE AUTHORITY": "state-owned (Santee Cooper)",
    "SANTEE COOPER": "state-owned (South Carolina)",
    "BASIN ELECTRIC POWER COOPERATIVE": "generation and transmission cooperative",
    "BASIN ELECTRIC": "generation and transmission cooperative",
    "ASSOCIATED ELECTRIC COOPERATIVE INC": "generation and transmission cooperative",
    "OGLETHORPE POWER CORP": "generation and transmission cooperative",
    "BUCKEYE POWER CO": "generation and transmission cooperative",
    "EAST KENTUCKY POWER COOPERATIVE": "generation and transmission cooperative",
    "SEMINOLE ELECTRIC COOPERATIVE INC": "generation and transmission cooperative",
    "ARKANSAS ELECTRIC COOPERATIVE CORP": "generation and transmission cooperative",
    "TRI-STATE GENERATION & TRANSMISSION ASSOC INC": "generation and transmission cooperative",
    "GREAT RIVER ENERGY": "generation and transmission cooperative",
    "BIG RIVERS ELECTRIC CORP": "generation and transmission cooperative",
    "OLD DOMINION ELECTRIC COOPERATIVE": "generation and transmission cooperative",
    "NEBRASKA PUBLIC POWER DISTRICT": "public power district",
    "OMAHA PUBLIC POWER DISTRICT": "public power district",
    "LOWER COLORADO RIVER AUTHORITY": "state river authority (Texas)",
    "PUERTO RICO ELECTRIC POWER AUTHORITY": "territorial public utility",
    "JEA": "municipal (Jacksonville, Florida)",
    "CITY OF SAN ANTONIO": "municipal (CPS Energy, San Antonio)",
    "ILLINOIS MUNICIPAL ELECTRIC AGENCY": "municipal joint action agency (Prairie State)",
    "INDIANA MUNICIPAL POWER AGENCY": "municipal joint action agency",
    "AMERICAN MUNICIPAL POWER INC": "municipal joint action agency",
    "INTERMOUNTAIN POWER AGENCY": "municipal joint action agency (Utah/California)",
    "PRAIRIE STATE ENERGY CAMPUS MANAGEMENT CO": "municipal joint venture",
    "OHIO VALLEY ELECTRIC CORP": "jointly owned by several utilities, no single listed parent",
    "KOCH INDUSTRIES INC": "private (Koch Industries)",
    "HILCORP ENERGY CO": "private (Hilcorp)",
    "LIGHTSTONE GENERATION LLC": "private equity (Blackstone / ArcLight)",
    "ARCLIGHT CAPITAL HOLDINGS LLC": "private equity (ArcLight)",
    "ARCLIGHT ENERGY PARTNERS FUND VII LP": "private equity (ArcLight)",
    "LS POWER DEVELOPMENT, LLC": "private equity (LS Power)",
    "LS POWER EQUITY PARTNERS LP": "private equity (LS Power)",
    "COVANTA HOLDING CORP": "private equity (EQT Infrastructure)",
    "COVANTA ENERGY": "private equity (EQT Infrastructure)",
    "GENON ENERGY INC": "private; emerged from Chapter 11 in 2018 and is creditor-owned",
    "GENON HOLDINGS INC": "private; emerged from Chapter 11 in 2018 and is creditor-owned",
    "TALEN ENERGY CORP": "US-listed (TLN) but not an S&P 500 constituent",
    "PBF ENERGY INC": "US-listed (PBF) but not an S&P 500 constituent",
    "ENERGY TRANSFER LP": "US-listed partnership (ET), not an S&P 500 constituent",
    "ENTERPRISE PRODUCTS PARTNERS LP": "US-listed partnership (EPD), not an S&P 500 constituent",
    "CLEVELAND-CLIFFS INC": "US-listed (CLF), removed from the S&P 500",
    "US STEEL CORP": "acquired by Nippon Steel in 2025, no longer US-listed",
    "UNITED STATES STEEL CORPORATION": "acquired by Nippon Steel in 2025, no longer US-listed",
    "EASTMAN CHEMICAL CO": "US-listed (EMN), removed from the S&P 500",
    "OGE ENERGY CORP": "US-listed (OGE), not an S&P 500 constituent",
    "ALLETE INC": "taken private in 2025",
    "CONSOL ENERGY INC": "US-listed (CEIX/CNR), not an S&P 500 constituent",
    "ALCOA INC": "US-listed (AA), not an S&P 500 constituent",
    "BP AMERICA INC": "foreign-listed parent (BP plc)",
    "SHELL OIL CO": "foreign-listed parent (Shell plc)",
    "SHELL PETROLEUM INC": "foreign-listed parent (Shell plc)",
    "ARCELORMITTAL USA": "foreign-listed parent (ArcelorMittal)",
    "HOLCIM PARTICIPATIONS (US) INC": "foreign-listed parent (Holcim)",
    "CEMEX INC": "foreign-listed parent (Cemex SAB)",
    "FORMOSA PLASTICS CORP USA": "foreign-listed parent (Formosa Plastics)",
    "AMERICAN AIR LIQUIDE HOLDINGS INC": "foreign-listed parent (Air Liquide)",
    "ARAMCO SERVICES CO": "state-owned (Saudi Aramco)",
    "PDV HOLDING INC": "state-owned (PDVSA / Citgo)",
    "GDF SUEZ ENERGY NORTH AMERICA INC": "foreign-listed parent (Engie)",
    "TAMPA ELECTRIC CO": "foreign-listed parent (Emera)",
    "TECO ENERGY INC": "foreign-listed parent (Emera)",
    "UNS ENERGY CORP": "foreign-listed parent (Fortis)",
    "NV ENERGY": "subsidiary of Berkshire Hathaway Energy, matched under BRK.B where EPA names it",
    "DOMTAR CORP": "private (Paper Excellence)",
    "ASCEND PERFORMANCE MATERIALS LLC": "private (SK Capital)",
    "GRAPHIC PACKAGING INTERNATIONAL INC": "US-listed (GPK), not an S&P 500 constituent",
    "PORTLAND GENERAL ELECTRIC CO": "US-listed (POR), not an S&P 500 constituent",
    "CLECO CORPORATE HOLDINGS LLC": "private (Macquarie-led consortium)",
    "PUGET HOLDINGS LLC": "private (Macquarie-led consortium)",
    "INVENERGY LLC": "private",
    "EAGLE MATERIALS INC": "US-listed (EXP), not an S&P 500 constituent",
    "HALLADOR ENERGY CO": "US-listed (HNRG), not an S&P 500 constituent",
    "CHENIERE ENERGY INC": "US-listed (LNG), not an S&P 500 constituent",
    "AMERICAN CONSOLIDATED NATURAL RESOURCES INC": "private (successor to Murray Energy)",
    "RC LONESTAR INC": "private",
    "EFS-N LLC": "private fund vehicle",
    "LOUISIANA GENERATING LLC": "sold out of NRG in 2019, now Cleco-owned and private",
    "WESTERN MIDSTREAM PARTNERS LP": "separately listed (WES); Occidental holds a minority of the units plus the general partner, so it is left unattributed rather than consolidated by hand",
    "NUTRIEN US TOPCO LLC": "foreign-listed parent (Nutrien, TSX/NYSE), not an S&P 500 constituent",
    "HF SINCLAIR CORP": "US-listed (DINO), not an S&P 500 constituent",
    "WESTLAKE CHEMICAL CORP": "US-listed (WLK), not an S&P 500 constituent",
    "BLACK HILLS CORP": "US-listed (BKH), not an S&P 500 constituent",
    "IDACORP": "US-listed (IDA), not an S&P 500 constituent",
    "HAWAIIAN ELECTRIC INDUSTRIES INC": "US-listed (HE), not an S&P 500 constituent",
    "WASTE CONNECTIONS US INC": "US-listed (WCN), not an S&P 500 constituent",
    "ENBRIDGE (US) INC": "foreign-listed parent (Enbridge)",
    "TRANSCANADA PIPELINE USA LTD": "foreign-listed parent (TC Energy)",
    "TRANSALTA USA INC": "foreign-listed parent (TransAlta)",
    "BASF CORP": "foreign-listed parent (BASF SE)",
    "NATIONAL GRID USA": "foreign-listed parent (National Grid plc)",
    "HEIDELBERG MATERIALS US CEMENT LLC": "foreign-listed parent (Heidelberg Materials)",
    "TAIHEIYO CEMENT USA INC": "foreign-listed parent (Taiheiyo Cement)",
    "LHOIST NORTH AMERICA": "private (Lhoist group, Belgium)",
    "CARMEUSE LIME INC": "private (Carmeuse group, Belgium)",
    "GRAYMONT INC": "private",
    "POET LLC": "private",
    "WHEELABRATOR TECHNOLOGIES HOLDINGS INC": "private equity (Macquarie)",
    "EDGEWATER GENERATION HOLDINGS LLC": "private equity",
    "ARGO INFRASTRUCTURE PARTNERS LP": "private equity",
    "OMNIS PLEASANTS, LLC": "private",
    "MIDLAND COGENERATION VENTURE": "private partnership",
    "REMC ASSETS LP": "private; Coal Creek Station, now operated by Rainbow Energy Center",
    "JACKSONVILLE ELECTRIC AUTHORITY": "municipal (Jacksonville, Florida)",
    "AUSTIN ENERGY": "municipal (Austin, Texas)",
    "ORLANDO UTILITIES COMMISSION": "municipal (Orlando, Florida)",
    "MINNKOTA POWER COOPERATIVE INC": "generation and transmission cooperative",
    "DESERET GENERATION & TRANSMISSION COOPERATIVE": "generation and transmission cooperative",
    "COOPERATIVE ENERGY A MISSISSIPPI ELECTRIC COOPERATIVE": "generation and transmission cooperative",
    "INDIANA-KENTUCKY ELECTRIC CORPORATION": "jointly owned by several utilities, no single listed parent",
    "GAVIN POWER, LLC": "private equity (Blackstone / ArcLight)",
    "RAINBOW ENERGY CENTER, LLC": "private",
    "TENNESSEE VALLEY AUTHORITY": "federal",
    "OKLAHOMA GAS & ELECTRIC COMPANY": "US-listed parent (OGE Energy), not an S&P 500 constituent",

    # Added by the entity-resolution audit. Each was verified against the facilities EPA files
    # under the string, because an unmatched emitter with no reason on it looks like a miss.
    "DEER PARK REFINING LP": "state-owned (Pemex bought Shell's half of the Deer Park refinery in 2022)",
    "HBM HOLDINGS CO": "private (Mississippi Lime)",
    "ARGOS USA LLC": "merged into Summit Materials in 2024, which Quikrete took private in 2025",
    "INEOS USA LLC": "private (INEOS)",
    "CVR ENERGY INC": "US-listed (CVI), not an S&P 500 constituent",
    "LONGVIEW INTERMEDIATE HOLDINGS C LLC": "private (Longview Power)",
    "CARLYLE GROUP MANAGEMENT LLC": "private equity; the plants are the Cogentrix fleet, and Carlyle is not an index constituent",
    "SUNCOKE ENERGY": "US-listed (SXC), not an S&P 500 constituent",
    "RAYONIER ADVANCED MATERIALS INC": "US-listed (RYAM), not an S&P 500 constituent",
    "AVISTA CORP": "US-listed (AVA), not an S&P 500 constituent",
    "SAPPI NORTH AMERICA INC": "foreign-listed parent (Sappi, Johannesburg)",
    "EL PASO ELECTRIC CO": "held by IIF, a JPMorgan-managed infrastructure fund; see the fund-owner rule",
    "DIVERSIFIED GAS & OIL CORP": "US-listed (DEC), not an S&P 500 constituent",
    "VENTURE GLOBAL LNG INC": "US-listed (VG) since 2025, not an S&P 500 constituent",
    "ARCH RESOURCES INC": "merged with CONSOL into Core Natural Resources (CNR), not an S&P 500 constituent",
    "WESTLAKE CORP": "US-listed (WLK), not an S&P 500 constituent",
    "PNM RESOURCES INC": "US-listed (TXNM), not an S&P 500 constituent",
    "DELEK US HOLDINGS INC": "US-listed (DK), not an S&P 500 constituent",
    "CLEARWATER PAPER CORP": "US-listed (CLW), not an S&P 500 constituent",
    "BILLERUD AMERICAS CORP": "foreign-listed parent (Billerud, Stockholm)",
    "CARGILL INC": "private (Cargill)",
    "CHS INC": "agricultural cooperative",
    "SYLVAMO NORTH AMERICA LLC": "US-listed (SLVM) since the 2021 International Paper spin, not an S&P 500 constituent",
    "CONTINENTAL RESOURCES INC": "private since the Hamm family took it private in 2022",
    "GFL ENVIRONMENTAL HOLDINGS (US) INC": "foreign-listed parent (GFL Environmental, Toronto)",
    "NORTHWESTERN CORP": "US-listed (NWE), not an S&P 500 constituent",
    "OTTER TAIL CORP": "US-listed (OTTR), not an S&P 500 constituent",
    "CALIFORNIA RESOURCES CORP": "US-listed (CRC), not an S&P 500 constituent",
    "TOTAL HOLDINGS USA INC": "foreign-listed parent (TotalEnergies)",
    "THE CHEMOURS CO": "US-listed (CC) since the 2015 DuPont spin, not an S&P 500 constituent",
    "GCC OF AMERICA INC": "foreign-listed parent (Grupo Cementos de Chihuahua)",
    "ALLIANCE HOLDINGS GP LP": "US-listed partnership (ARLP), not an S&P 500 constituent",
    "EAGLECLAW MIDSTREAM SERVICES LLC": "US-listed (KNTK) after the Kinetik combination, not an S&P 500 constituent",
    "OSAKA GAS USA CORP": "foreign-listed parent (Osaka Gas)",
    "J POWER USA DEVELOPMENT CO LTD": "foreign-listed parent (J-POWER)",
    "GENERATION HOLDINGS LP": "private; Seward and Colver, Pennsylvania waste-coal plants",
    "ASTORIA PROJECT PARTNERS LLC": "private project company (Astoria Energy)",
    "CASEY CO": "private; Kern Energy, a Bakersfield refinery, not Casey's General Stores (CASY)",
    "ENERGY HARBOR CORP": "W H Sammis and Pleasants, both sold on before Vistra bought the rest of Energy Harbor in 2024",
    "WASTE INDUSTRIES USA INC": "acquired by GFL Environmental in 2018, not by Waste Management",
    "E I DU PONT DE NEMOURS & CO": "legacy DuPont; most of the tonnage went to Chemours in 2015 and to Dow in 2019",
    "TENASKA INC": "private (Tenaska)",
    "AEP GENERATION RESOURCES INC": "CAMD still names it as owner of Cardinal Unit 1, but AEP sold that unit to Buckeye Power in August 2022 and GHGRP already books the whole plant to Buckeye",
}
