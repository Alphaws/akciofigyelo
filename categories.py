import re
import unicodedata

def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', str(text).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace("0", "o").replace("1", "i")

TAXONOMY_TREE = {
    "tejtermek": {
        "title": "Tejtermékek",
        "icon": "fa-solid fa-cow",
        "subs": {
            "tej": "Tej (UHT, ESL, Friss)",
            "tejfol": "Tejföl és Frissföl",
            "sajt": "Sajtok (Trappista, Gouda, Mozzarella...)",
            "vaj_margarin": "Vaj, Vajkrém és Margarin",
            "turo_desszert": "Túró és Tejes Desszertek",
            "joghurt_kefir": "Joghurt és Kefir",
            "tejszin": "Tejszín és Habtejszín",
            "novenyi_helyettesito": "Növényi tej- és sajthelyettesítők"
        }
    },
    "tojas": {
        "title": "Tojás",
        "icon": "fa-solid fa-egg",
        "subs": {
            "friss_tojas": "Friss étkezési tojás",
            "furdotojas": "Fürjtojás és egyéb tojás"
        }
    },
    "hus_hal": {
        "title": "Hús, Hal és Felvágott",
        "icon": "fa-solid fa-drumstick-bite",
        "subs": {
            "csirke_szarnyas": "Csirke és Szárnyashús (Pulyka, Kacsa)",
            "sertes": "Sertéshús (Karaj, Tarja, Comb, Oldalas)",
            "marha": "Marhahús és Borjú",
            "hal": "Halak és Tengeri termékek",
            "felvagott_felkesz": "Felvágottak, Szalámik, Virslik, Szalonna"
        }
    },
    "pekaru": {
        "title": "Pékáru",
        "icon": "fa-solid fa-bread-slice",
        "subs": {
            "kenyer": "Kenyérfélék (Fehér, Félbarna, Rozs, Toast)",
            "peksutemeny": "Péksütemények (Zsemle, Kifli, Csiga)"
        }
    },
    "zoldseg_gyumolcs": {
        "title": "Zöldség és Gyümölcs",
        "icon": "fa-solid fa-apple-whole",
        "subs": {
            "zoldseg": "Friss és fagyasztott zöldségek, Burgonya",
            "gyumolcs": "Friss és szárított gyümölcsök"
        }
    },
    "alapveto_elelmiszer": {
        "title": "Alapvető Élelmiszer & Édesség",
        "icon": "fa-solid fa-wheat-awn",
        "subs": {
            "liszt_cukor_teszta": "Liszt, Cukor, Tészta, Rizs",
            "olaj_ecet_zsir": "Étolaj, Olívaolaj és Zsírok",
            "konzerv_keszetel": "Konzervek, Hüvelyesek, Szószok",
            "kave_tea_edesseg": "Kávé, Tea, Csokoládé, Keksz"
        }
    },
    "italok": {
        "title": "Italok",
        "icon": "fa-solid fa-bottle-water",
        "subs": {
            "alkoholmentes": "Ásványvíz, Üdítők, Gyümölcslevek",
            "alkoholos": "Sörök, Borok, Égetett szeszek"
        }
    },
    "haztartas_vegyi": {
        "title": "Háztartás és Vegyiáru",
        "icon": "fa-solid fa-spray-can-sparkles",
        "subs": {
            "tisztitoszer": "Mosó- és tisztítószerek, Mosogatás",
            "papiraru": "Papíráru (Toalettpapír, Zsebkendő)"
        }
    },
    "szepseg_baba": {
        "title": "Szépségápolás és Baba",
        "icon": "fa-solid fa-baby",
        "subs": {
            "tisztalkodas": "Tusfürdő, Sampon, Fogápolás, Borotválkozás",
            "babaapolas": "Pelenkák, Babápolás, Bébiétel"
        }
    },
    "nem_elelmiszer": {
        "title": "Nem élelmiszer (Barkács, Otthon)",
        "icon": "fa-solid fa-wrench",
        "subs": {
            "barkacs_elektronika": "Szerszámok, Elektronika, Háztartási gépek"
        }
    },
    "egyeb": {
        "title": "Egyéb termékek",
        "icon": "fa-solid fa-box",
        "subs": {
            "egyeb": "Egyéb akciós termékek"
        }
    }
}

KEYWORD_RULES = [
    # TOJAS
    ("tojas", "friss_tojas", ["tojas", "furjtojas", "tojasok"]),

    # TEJTERMEK
    ("tejtermek", "tejfol", ["tejfol", "frissfol", "creme fraiche", "creme vega"]),
    ("tejtermek", "tej", ["tej", "uht", "esl", "tejital", "zsíros tej"]),
    ("tejtermek", "sajt", [
        "sajt", "trappista", "gouda", "edami", "cheddar", "mozzarella", "brie", 
        "camembert", "ementali", "feta", "parmezan", "tilsit", "omlesztett", 
        "mascarpone", "ricotta", "kaskaval", "provolone", "parmigiano", "grana padano", 
        "bryndza", "kremfehersajt", "kashkaval", "fustolt sajt"
    ]),
    ("tejtermek", "vaj_margarin", ["vaj", "vajkrem", "margarin", "rama", "delma", "flora", "szendvicskrem", "teavaj"]),
    ("tejtermek", "turo_desszert", ["turo", "tehenturo", "turodesszert", "kremturo", "turo rudi", "puding", "desszert", "monte", "kinder"]),
    ("tejtermek", "joghurt_kefir", ["joghurt", "ivojoghurt", "kefir", "aludttej", "kaukazusi", "actimel", "activia", "tzatziki"]),
    ("tejtermek", "tejszin", ["tejszin", "habtejszin", "fozotejszin", "habspray"]),

    # HUS ES HAL
    ("hus_hal", "csirke_szarnyas", ["csirke", "grillcsirke", "pulyka", "kacsa", "liba", "szarnyas", "kakas", "galamb"]),
    ("hus_hal", "marha", ["marha", "borju", "feherpecsenye", "marhalabszar", "gulyashus", "rostelyos", "felsal"]),
    ("hus_hal", "hal", ["hal", "harcsa", "ponty", "lazac", "hekk", "tonhal", "tengeri", "garnela", "makrela", "pisztrang", "hering", "sullo", "fogas", "halrud"]),
    ("hus_hal", "sertes", ["sertes", "karaj", "tarja", "oldalas", "comb", "szuzpecsenye", "kocsonyahus", "csaszar", "dagado", "lapocka", "angolszalonna"]),
    ("hus_hal", "felvagott_felkesz", [
        "parizsi", "sonka", "szalami", "teliszalami", "kolbasz", "virsli", "fustli", 
        "szalonna", "majas", "kenomajas", "felvagott", "prosciutto", "bacon", 
        "mortadella", "tepert", "disznosajt", "hurka", "cabanossi", "debreceni", "pikok"
    ]),

    # PEKARU
    ("pekaru", "kenyer", ["kenyer", "cipo", "vekni", "toast", "durumvekni", "búzacipó"]),
    ("pekaru", "peksutemeny", ["zsemle", "kifli", "brios", "kalacs", "kakaoscsiga", "croissant", "pogacsa", "perec", "fank", "bagett", "retesszel"]),

    # ZOLDSEG & GYUMOLCS
    ("zoldseg_gyumolcs", "zoldseg", [
        "burgonya", "krumpli", "edesburgonya", "hagyma", "voroshagyma", "lilahagyma", "ujhagyma", 
        "fokhagyma", "paprika", "zoldpaprika", "paradicsom", "repa", "sargarepa", "feherrepa", 
        "petrezselyem", "uborka", "kigyouborka", "kaposzta", "salata", "jegsalata", "rukkola", 
        "tok", "sutotok", "cekla", "brokkoli", "karfiol", "cukkini", "padlizsan", "gomba", 
        "spenot", "soska", "retek", "zeller", "gyomber", "karalabe", "leveszoldseg", "zoldhagyma"
    ]),
    ("zoldseg_gyumolcs", "gyumolcs", [
        "alma", "korte", "banan", "citrom", "narancs", "eper", "szolo", "szilva", "barack", 
        "oszi", "kajszi", "mandarin", "grapefruit", "klementin", "kiwi", "avokado", "ananasz", 
        "dio", "mandula", "mogyoro", "mazsola", "gesztenye", "afonya", "malna", "granatalma", "fuge"
    ]),

    # ALAPVETO ELELMISZER
    ("alapveto_elelmiszer", "olaj_ecet_zsir", ["etolaj", "oliva", "zsir", "napraforgo", "ecet", "kokoszzsir", "repceolaj"]),
    ("alapveto_elelmiszer", "liszt_cukor_teszta", [
        "liszt", "cukor", "porcukor", "kristalycukor", "teszta", "spagetti", "makaroni", 
        "penne", "rizs", "dara", "zsemlemorzsa", "zabpehely", "muszli", "gabona"
    ]),
    ("alapveto_elelmiszer", "konzerv_keszetel", ["konzerv", "kukorica", "bab", "borso", "savanyusag", "martas", "szosz", "ecetes", "surgitett"]),
    ("alapveto_elelmiszer", "kave_tea_edesseg", [
        "kave", "tea", "kakao", "csokolade", "keksz", "chips", "tortillachips", "edesseg", 
        "cukorka", "nasi", "csoki", "gofri", "puszedli", "mamba", "gumicukor", "napolyi", 
        "ostya", "mentos", "raffaello", "ferrero", "haribo", "bonbon", "waffelini", "milka"
    ]),

    # ITALOK
    ("italok", "alkoholos", ["sor", "bor", "pezsgo", "palinka", "vodka", "whisky", "gin", "likor", "rum"]),
    ("italok", "alkoholmentes", ["viz", "asvanyviz", "udito", "szoda", "gyumolcsle", "gyumolcsital", "multivitaminle", "szorp", "energiaital", "cola", "fanta", "sprite", "siro", "cappy"]),

    # HAZTARTAS
    ("haztartas_vegyi", "tisztitoszer", ["mosopor", "mososzer", "oblito", "mosogato", "tisztito", "surolo", "domestos", "ariel", "persil", "somat", "jar"]),
    ("haztartas_vegyi", "papiraru", ["toalettpapir", "wc-papir", "zsebkendo", "papirkeztorlo", "alufolia", "szalveta", "sutopapir"]),

    # SZEPSEG & BABA
    ("szepseg_baba", "tisztalkodas", ["tusfurdo", "sampon", "szappan", "fogkrem", "fogkefe", "dezodor", "borotva", "testapolo", "intim"]),
    ("szepseg_baba", "babaapolas", ["pelenka", "popsitorlo", "bebietel", "tapszer", "baba", "lupilu"]),

    # NON-FOOD
    ("nem_elelmiszer", "barkacs_elektronika", ["parkside", "tronic", "tefal", "vasalo", "korfuresz", "akkus", "fuszegelynyiro", "eloszto", "inditasrasegito", "torolkozoszarito", "lampa", "elem"])
]

def map_gvh_category(gvh_path: str):
    if not gvh_path or gvh_path.startswith("akcios_ujsag/"):
        return None
    parts = gvh_path.split("/")
    main_p = parts[0]
    sub1 = parts[1] if len(parts) > 1 else ""
    sub2 = parts[2] if len(parts) > 2 else ""

    if main_p == "tejtermek_sajt_tojas":
        if sub1 == "tojasok":
            return ("tojas", "friss_tojas")
        elif sub1 == "tej":
            return ("tejtermek", "tej")
        elif sub1 == "tejfol":
            return ("tejtermek", "tejfol")
        elif sub1 == "sajt":
            return ("tejtermek", "sajt")
        elif sub1 == "vaj_vajkrem_margarin":
            return ("tejtermek", "vaj_margarin")
        elif sub1 in ["joghurt_turo_kefir", "tejdesszert"]:
            if "turo" in sub2:
                return ("tejtermek", "turo_desszert")
            return ("tejtermek", "joghurt_kefir")
        elif sub1 == "tejszin":
            return ("tejtermek", "tejszin")
        return ("tejtermek", "sajt")

    elif main_p == "hus_hal_felvagott":
        if sub1 == "szarnyas":
            return ("hus_hal", "csirke_szarnyas")
        elif sub1 == "sertes":
            return ("hus_hal", "sertes")
        elif sub1 == "marha":
            return ("hus_hal", "marha")
        elif sub1 == "hal":
            return ("hus_hal", "hal")
        elif sub1 in ["felvagott", "kolbasz", "virsli", "szalonna", "egyeb_huskeszitmeny"]:
            return ("hus_hal", "felvagott_felkesz")
        return ("hus_hal", "sertes")

    elif main_p == "pekaru":
        if sub1 == "kenyerfelek":
            return ("pekaru", "kenyer")
        return ("pekaru", "peksutemeny")

    elif main_p == "zoldseg_gyumolcs":
        if sub1 == "gyumolcs":
            return ("zoldseg_gyumolcs", "gyumolcs")
        return ("zoldseg_gyumolcs", "zoldseg")

    elif main_p == "tartos_elelmiszer_ital":
        if sub1 == "liszt_cukor_olaj":
            if "olaj" in sub2:
                return ("alapveto_elelmiszer", "olaj_ecet_zsir")
            return ("alapveto_elelmiszer", "liszt_cukor_teszta")
        elif sub1 in ["teszta_haztartasikeksz", "rizs"]:
            return ("alapveto_elelmiszer", "liszt_cukor_teszta")
        elif sub1 in ["konzerv_savanyusag", "huvelyesek_magvak"]:
            return ("alapveto_elelmiszer", "konzerv_keszetel")
        elif sub1 in ["tea_kave", "kakao"]:
            return ("alapveto_elelmiszer", "kave_tea_edesseg")
        elif sub1 == "viz_gyumolcsle":
            return ("italok", "alkoholmentes")
        return ("alapveto_elelmiszer", "liszt_cukor_teszta")

    elif main_p == "haztartas":
        if sub1 == "haztartasi_papiraru_csomagolo":
            return ("haztartas_vegyi", "papiraru")
        return ("haztartas_vegyi", "tisztitoszer")

    elif main_p == "szepseg_higienia":
        return ("szepseg_baba", "tisztalkodas")

    elif main_p == "baba":
        return ("szepseg_baba", "babaapolas")

    elif main_p == "specialis_etrend":
        if "laktozmentes" in sub1:
            if "tejfol" in sub2: return ("tejtermek", "tejfol")
            if "sajt" in sub2: return ("tejtermek", "sajt")
            if "vaj" in sub2: return ("tejtermek", "vaj_margarin")
            if "turo" in sub2: return ("tejtermek", "turo_desszert")
            if "joghurt" in sub2 or "kefir" in sub2: return ("tejtermek", "joghurt_kefir")
            if "tej" in sub2: return ("tejtermek", "tej")
            return ("tejtermek", "tej")
        elif "novenyi" in sub1:
            return ("tejtermek", "novenyi_helyettesito")
        elif "glutenmentes" in sub1:
            if "kenyer" in sub2: return ("pekaru", "kenyer")
            return ("alapveto_elelmiszer", "liszt_cukor_teszta")
        return ("alapveto_elelmiszer", "liszt_cukor_teszta")

    return None

def resolve_product_categories(name: str, category_path: str = "") -> tuple[str, str]:
    mapped = map_gvh_category(category_path)
    if mapped:
        return mapped

    norm = normalize(name)
    for main_c, sub_c, keywords in KEYWORD_RULES:
        for kw in keywords:
            kw_norm = normalize(kw)
            if re.search(r'\b' + re.escape(kw_norm), norm):
                return (main_c, sub_c)

    return ("egyeb", "egyeb")
