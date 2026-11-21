"""HTML parsing for cavliwireless.com pages (copied from the Assignment 1 project, ingest/cavli26.py; fetch/build parts kept
but unused here). Used for the product page and the category page."""
import hashlib, json, re, sys, uuid
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cavli26"
RAW = DATA / "raw"
BASE = "https://www.cavliwireless.com"
UA = {"User-Agent": "Mozilla/5.0 (compatible; cavli-assistant-poc/0.2)"}
COLLECTION = "cavli_modules"

# ------------------------------------------------------------------ the 26 pages
CATEGORIES = {  # slug -> (category name, path)
    "5g-redcap": ("5G RedCap", "iot-modules/5g-redcap-iot-module"),
    "lte-cat4": ("LTE Cat 4", "iot-modules/lte-Cat4-iot-module"),
    "lte-cat1": ("LTE Cat 1", "iot-modules/lte-Cat1-iot-module"),
    "5g-nr": ("5G NR", "iot-modules/5g-nr-iot-module"),
    "lpwa": ("LPWA", "iot-modules/lpwa-iot-module"),
    "automotive": ("Automotive", "iot-modules/automotive-grade-iot-module"),
    "lte-cat1bis": ("LTE Cat 1bis", "iot-modules/lte-Cat1-bis-iot-module"),
}
PRODUCTS = {  # product -> (series, categories, slug)
    "CQM220": ("c-series", ["5G RedCap"], "cqm220"),
    "CQ20": ("c-series", ["LTE Cat 4"], "cq20"),
    "CQS292": ("c-series", ["LTE Cat 4"], "cqs292"),
    "C20QM": ("c-series", ["LTE Cat 4"], "c20qm"),
    "CQS315": ("c-series", ["LTE Cat 4"], "cqs315"),
    "CQS290": ("c-series", ["LTE Cat 4"], "cqs290"),
    "CQS291": ("c-series", ["LTE Cat 4"], "cqs291"),
    "C10QM": ("c-series", ["LTE Cat 1"], "c10qm"),
    "CQ10": ("c-series", ["LTE Cat 1"], "cq10"),
    "C11QM": ("c-series", ["LTE Cat 1"], "c11qm"),
    "CQM211": ("c-series", ["5G NR"], "cqm211"),
    "CQM212": ("c-series", ["5G NR"], "cqm212"),
    "CQM215": ("c-series", ["5G NR"], "cqm215"),
    "C41QS": ("c-series", ["LPWA"], "c41qs"),
    "AQ62": ("a-series", ["Automotive", "5G NR"], "aq62"),
    "AQ65": ("a-series", ["Automotive", "5G NR"], "aq65"),
    "CQ16": ("c-series", ["LTE Cat 1bis"], "cq16"),
    "C16QS": ("c-series", ["LTE Cat 1bis"], "c16qs"),
    "P16QS": ("c-series", ["LTE Cat 1bis"], "p16qs"),
}
CAT_SLUG = {v[0]: k for k, v in CATEGORIES.items()}


def product_url(p):
    series, _, slug = PRODUCTS[p]
    return f"{BASE}/iot-modules/{series}/{slug}"


MODULE_PAGES = {p: product_url(p) for p in PRODUCTS}


CONTACT_URL = f"{BASE}/contact-us"


def category_url(name):
    return f"{BASE}/{CATEGORIES[CAT_SLUG[name]][1]}"


# Region codes as the site prints them (cat-page table, regional-code lists, FAQs). "EA" is printed as "East Asia"
# on most pages but "Europe-Asia" on AQ62/AQ65 - that disagreement is reported in conflicts.json.
REGIONS = {"WW": "Worldwide", "NA": "North America", "EAJ": "Eurasia & Japan", "EA": "East Asia", "EU": "Europe",
           "IN": "India", "AN": "Australia & New Zealand", "LA": "Latin America"}
REGION_ALIAS = {"GLOBAL": "WW", "WORLDWIDE": "WW", "WORLD WIDE": "WW", "INDIA": "IN"}
_REG_RE = "EAJ|EA|NA|EU|IN|AN|LA|WW"

NORMALIZATIONS = Counter()


def fix(s):
    """Whitespace + the known site typos (logged in NORMALIZATIONS -> data/cavli26/normalizations.json)."""
    s = re.sub(r"\s+", " ", s or "").strip()
    for pat, rep, tag in [
        (r"\bKyro\b", "Kryo", "Kyro->Kryo"),
        (r"(?<![A-Za-z0-9])12S\b|(?<=\dx)12S\b", "I2S", "12S->I2S"),
        (r"Wi-FI", "Wi-Fi", "Wi-FI->Wi-Fi"),
        (r"\bBDU\b", "BDS", "BDU->BDS"),
        (r"AdrenoTM", "Adreno™", "AdrenoTM->Adreno™"),
        (r"\b(package)\d\b", r"\1", "package<footnote digit>"),
        (r"(\d)(Kbps|Mbps|Gbps)", r"\1 \2", "unit spacing"),
        (r"\b(Gbps|Mbps)\s+(Mbps|Gbps)\b", r"\1", "'Gbps Mbps' -> single unit"),
        (r"\bdeploymnet\b", "deployment", "deploymnet->deployment"),
    ]:
        s, n = re.subn(pat, rep, s, flags=re.I if tag == "package<footnote digit>" else 0)
        if n:
            NORMALIZATIONS[tag] += n
    s = re.sub(r'"\s+([^"]+?)\s+"', r'"\1"', s)
    s = re.sub(r"\s+([.,;:!?)\]])", r"\1", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    return s


# ------------------------------------------------------------------ fetching
def fetch(key, url, refresh=False):
    RAW.mkdir(parents=True, exist_ok=True)
    f = RAW / f"{key}.html"
    if f.exists() and not refresh:
        return f.read_text(encoding="utf-8")
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    f.write_text(r.text, encoding="utf-8")
    return r.text


def soup(html):
    s = BeautifulSoup(html, "html.parser")
    for t in s(["script", "style", "noscript", "svg"]):
        t.decompose()
    return s


def lines_of(el):
    return [x.strip() for x in el.get_text("\n", strip=True).split("\n") if x.strip()] if el else []


def para(el):
    return fix(el.get_text(" ", strip=True))


def rich(el):
    """Paragraphs and list items of an element as text lines (bullets kept as '- ')."""
    out = []
    for c in el.find_all(["p", "li", "ul", "ol"]):
        if c.name in ("ul", "ol"):
            continue
        if c.name == "p" and c.find_parent("li"):
            continue
        t = para(c)
        if t:
            out.append(("- " + t) if c.name == "li" else t)
    return out or ([para(el)] if para(el) else [])


def dedupe(items):
    seen, out = set(), []
    for i in items:
        k = re.sub(r"\W+", "", i.lower())
        if k and k not in seen:
            seen.add(k)
            out.append(i)
    return out


# ------------------------------------------------------------------ mentions
KNOWN = set(PRODUCTS)
_TOKEN = re.compile(r"\b(?:CQM\d{3}|CQS\d{3}|CQ\d{2}|AQ\d{2}|[CP]\d{2}[A-Z]{2})\b")


def mentions(text, self_product=None):
    found = set(_TOKEN.findall(text))
    known = sorted(found & KNOWN - {self_product})
    legacy = sorted(found - KNOWN - {self_product})
    return known, legacy


# ------------------------------------------------------------------ technical-data parsing
def pairs(lines):
    """['WW',':','LTE',':','1/2','NR',':','3/4'] -> [('WW',''),('LTE','1/2'),('NR','3/4')]  (label ':' value...)."""
    out, i, n = [], 0, len(lines)
    while i < n:
        if i + 1 < n and lines[i + 1] == ":":
            label = lines[i].rstrip(":").strip()
            i += 2
            val = []
            while i < n and not (i + 1 < n and lines[i + 1] == ":"):
                val.append(lines[i])
                i += 1
            out.append((label, " ".join(val).strip()))
        else:
            i += 1
    return out


def tech_sections(lines):
    sec, cur = {}, None
    names = {"Cellular Bands Supported": "bands", "Supported Location Services": "gnss", "OS": "os",
             "Packaging": "packaging", "Interfaces": "interfaces", "Key Highlights": "highlights"}
    for l in lines:
        key = names.get(l) or ("speeds" if l.startswith("Cellular Connectivity") else None)
        if key:
            cur = key
            sec[cur] = []
        elif l == "*" and cur == "interfaces":
            break
        elif cur:
            sec[cur].append(l)
    return sec


def clean_bands(v):
    v = fix(v)
    v = re.sub(r",\s*/", "/", v)
    v = re.sub(r"\s*/\s*", "/", v)
    v = re.sub(r"(\b[BnN]?\d+[A-Za-z]?)\*", r"\1 (optional)", v)
    return v


def parse_bands(lines):
    """-> list of {region, tech, bands}. Handles region:bands, region:tech:bands, tech:bands, and 'EA - ... NA - ...'."""
    entries, region, open_region, extras = [], None, False, []
    for label, val in pairs(lines):
        key = label.upper()
        reg = REGION_ALIAS.get(key, key if key in REGIONS else None)
        if reg:
            region, open_region = reg, val == ""
            if val:
                entries.append((region, None, val))
        elif label.lower().startswith("3gpp release"):
            extras.append(f"{label}: {fix(val)}")
        else:
            entries.append((region if open_region else None, label, val))
    out = []
    for region, tech, val in entries:
        # "EA - n1/n3 NA - n2/n5" : regions embedded inside one value
        embedded = list(re.finditer(rf"\b({_REG_RE})\s*-\s*(.*?)(?=\s\b(?:{_REG_RE})\s*-\s|$)", val))
        if embedded:
            for m in embedded:
                out.append(dict(region=m.group(1), tech=tech, bands=clean_bands(m.group(2))))
            continue
        multi = re.split(r",?\s*\b(LTE|NR|5G|4G)\s*:\s*", val)  # category cards: "LTE:1/2, NR: 1/2"
        if len(multi) > 2:
            for i in range(1, len(multi) - 1, 2):
                out.append(dict(region=region, tech=multi[i], bands=clean_bands(multi[i + 1])))
            continue
        m = re.match(r"^(LTE|NR|5G|4G)\s*-\s*(.*)$", val)
        if m:
            tech, val = tech or m.group(1), m.group(2)
        parts = [p.strip() for p in val.split("|")]
        out.append(dict(region=region, tech=tech, bands=clean_bands(parts[0])))
        for extra in parts[1:]:
            mm = re.match(r"^(GSM)\s*[–-]\s*(.*)$", extra)
            out.append(dict(region=region, tech=mm.group(1) if mm else "other", bands=fix(mm.group(2) if mm else extra)))
    return out, extras


def split_commas(s):
    items, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch in ",|" and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    return [i.strip() for i in items if i.strip()]


def parse_interfaces(text):
    """'1xLCD (DSI)**, 3xUART' -> ['1xLCD (DSI) (requires SDK)', '3xUART']  (* = optional, ** = requires SDK)."""
    out = []
    for it in split_commas(fix(text)):
        m = re.match(r"^(.*?)(\*{1,2})$", it)
        if m:
            it = f"{m.group(1).strip()} ({'requires SDK' if len(m.group(2)) == 2 else 'optional'})"
        out.append(it)
    return out


def parse_variants(lines, product):
    """Two page formats: SKU list (Modules/GNSS/eSIM/Flash) and the part-number decoder (Parameter/Options/Description)."""
    if "Parameter" in lines[:5]:
        names = {"Product", "Region SKU", "RF Config.", "Memory", "GNSS", "eSIM + Hubble", "HSM"}
        rows, cur = [], None
        for l in lines[lines.index("Description") + 1:]:
            if l in names and (cur is None or cur.get("options") is not None):
                cur = dict(param=l, options=None, desc=[])
                rows.append(cur)
            elif cur is not None:
                if cur["options"] is None:
                    cur["options"] = fix(l)
                else:
                    cur["desc"].append(l)
        for r in rows:
            d, i = [], 0
            while i < len(r["desc"]):
                t = r["desc"][i]
                if t.endswith(":") and i + 1 < len(r["desc"]):
                    d.append(f"{t[:-1]} = {fix(r['desc'][i + 1]).rstrip('·').strip()}")
                    i += 2
                else:
                    d.append(fix(t).rstrip("·").strip())
                    i += 1
            r["decoded"] = d
            del r["desc"]
        return dict(format="decoder", rows=rows)
    skus, cur, regional, variant_codes, note, mode = [], None, [], [], [], None
    for l in lines:
        if re.match(rf"^{re.escape(product)}-[A-Za-z0-9-]+$", l):
            cur = dict(sku=l, attrs=[])
            skus.append(cur)
            mode = "sku"
        elif l.startswith("Regional Codes"):
            mode = "regional"
        elif l.startswith("Variant Codes"):
            mode = "variant"
        elif l == "*":
            mode = "note"
        elif l.startswith("Related Case"):
            break
        elif mode == "sku":
            cur["attrs"].append(fix(l))
        elif mode == "regional":
            regional.append(fix(l))
        elif mode == "variant":
            variant_codes.append(fix(l))
        elif mode == "note":
            note.append(fix(l))
    for s_ in skus:
        a = s_["attrs"]
        s_["attrs"] = {a[i]: a[i + 1] for i in range(0, len(a) - 1, 2)}
    return dict(format="skus", skus=skus, regional=regional, variant_codes=variant_codes, note=" ".join(note))


# ------------------------------------------------------------------ product page
TOPICS = [  # first match on the question, then on the answer
    ("purchase", r"\b(buy|order|purchase|price|pricing|sample|samples|distributor|evk|quote|lead time|availability|available for)\b"),
    ("variants", r"\b(variant|variants|sku|skus|part number|memory option)\b"),
    ("hubble", r"\b(hubble|esim|fota|dfota|mqtt|device management|remote sim)\b"),
    ("voice/sms", r"\b(volte|vonr|voice|sms|ecall|ng-ecall|telephony)\b"),
    ("gnss", r"\b(gnss|gps|beidou|glonass|galileo|navic|positioning|location|qzss)\b"),
    ("power", r"\b(power|psm|edrx|battery|sleep|low-power|low power|energy)\b"),
    ("processor", r"\b(cpu|processor|cortex|kryo|gpu|adreno|core|cores|quad-core|octa-core)\b"),
    ("interfaces", r"\b(interface|interfaces|uart|usb|i2c|spi|gpio|camera|display|lcd|pcie|ethernet|sgmii|peripheral|audio)\b"),
    ("bands", r"\b(band|bands|frequency|frequencies|region|regional|spectrum|carrier|certif)\w*"),
]


def topic_of(question, answer=""):
    for text in (question.lower(), answer.lower()):
        for name, pat in TOPICS:
            if re.search(pat, text):
                return name
    return "general"


def faq_items(s):
    out = []
    for box in s.select("div.qnas"):
        qs, ds = box.select("h4"), box.select("div.description")
        for q, d in zip(qs, ds):
            lines = rich(d)
            question = fix(q.get_text(" ", strip=True))
            if question and lines:
                out.append(dict(question=question, answer="\n".join(lines)))
    return out


def parse_product(name, html):
    s = soup(html)
    series, cats, slug = PRODUCTS[name]
    hero = lines_of(s.select_one("#top"))
    skip = {"SCROLL", "Pre Order Evks", "Order Samples", "View in 3D", "Optional Feature", "Optional Features"}
    tags = [h for h in hero if h != name and h not in skip and not h.startswith("Available form-factor")]
    release = next((t for t in tags if t.startswith("3GPP Release")), None)
    labels = [t for t in tags if t != release]
    about_el = s.select_one("#about")
    about = [para(p) for p in about_el.find_all("p")] if about_el else []
    about = [a for a in about if a]
    hl = [x for x in lines_of(s.select_one("#key-highlights")) if x != "Key Highlights"]
    ff = [x for x in lines_of(s.select_one("#available-formfactors")) if not x.startswith("Available Form-Factor")]
    tech = tech_sections(lines_of(s.select_one("#technical-data")))
    uses = [x for x in lines_of(s.select_one("#applicable-industries")) if not x.startswith("Use Cases")]
    vel = s.select_one("#available-variants")
    vlines = lines_of(vel)
    if not vlines and about_el:  # AQ62/AQ65: the decoder table sits inside the About block
        al = lines_of(about_el)
        marker = next((i for i, x in enumerate(al) if x.startswith("Variants Available")), None)
        vlines = al[marker:] if marker is not None else []
    vlines = [x for x in vlines if not x.startswith("Variants Available")]
    variants = parse_variants(vlines, name) if vlines else None
    brochure = next((urljoin_base(a["href"]) for a in s.find_all("a", href=True) if "brochure" in a["href"].lower()), None)
    bands, band_extra = parse_bands(tech.get("bands", []))
    return dict(
        product=name, series=series, categories=cats, url=product_url(name), release=release, labels=labels,
        about=about, highlights=dedupe([fix(x) for x in hl]), form_factors=[fix(x) for x in ff],
        bands=bands, band_extra=band_extra,
        gnss=fix(" ".join(tech.get("gnss", []))), os=fix(" ".join(tech.get("os", []))),
        speeds=[(fix(l), fix(v)) for l, v in pairs(tech.get("speeds", []))],
        packaging=[(fix(l), fix(v)) for l, v in pairs(tech.get("packaging", []))],
        interfaces=parse_interfaces(" ".join(tech.get("interfaces", []))),
        use_cases=dedupe([fix(x) for x in uses]), variants=variants, brochure_url=brochure, faqs=faq_items(s),
    )


def urljoin_base(href):
    return href if href.startswith("http") else BASE + href


# ------------------------------------------------------------------ category page
def table_rows(t):
    """-> (heads, rows[(group, label, [cells])]). Single-cell rows are group headers, all-empty rows end a group."""
    raw = []
    for tr in t.find_all("tr"):
        raw.append([fix(" ; ".join(x.strip() for x in c.get_text("\n", strip=True).split("\n") if x.strip())
                        ).replace(",;", ";").replace("|", "/").replace("Technolog y", "Technology")
                    for c in tr.find_all(["th", "td"])])
    if not raw:
        return [], []
    heads, rows, group = raw[0], [], ""
    for r in raw[1:]:
        if not any(r):
            group = ""
            continue
        label = re.sub(r"^[-–]\s*", "", r[0])
        if label.lower() == "product image":
            continue
        if len(r) == 1 or (len(r) > 1 and not any(r[1:])):
            group = label
            continue
        if len(r) == 2 and len(heads) > 2:  # a full-width row (e.g. "Recommended applications")
            rows.append((group, label, [r[1]] * (len(heads) - 1)))
            continue
        rows.append((group, label, r[1:]))
    return heads, rows


def table_text(heads, rows):
    out = []
    for group, label, cells in rows:
        pre = f"{group} / " if group else ""
        out.append(f"{pre}{label} | " + " | ".join(f"{heads[i + 1]}: {c or '-'}" for i, c in enumerate(cells) if i + 1 < len(heads)))
    return " | ".join(heads) + "\n" + "\n".join(out)


def table_facts(heads, rows):
    """{product: {"group / label": value}} for product-column tables (heads[0] == 'Product')."""
    if not heads or heads[0].lower() != "product":
        return {}
    facts = {h: {} for h in heads[1:] if h}
    for group, label, cells in rows:
        for i, c in enumerate(cells):
            if i + 1 < len(heads) and heads[i + 1] in facts and c not in ("", "-"):
                facts[heads[i + 1]][f"{group} / {label}" if group else label] = c
    return facts


def parse_category(cat, html):
    s = soup(html)
    for el in s.select(".cta-block"):  # promo callouts
        el.decompose()
    top = s.select_one("#top")
    intro = []
    if top:
        for p in top.find_all(["p", "h2"]):
            t = para(p)
            if t and t != cat and not t.startswith("Order") and len(t) > 40:
                intro.append(t)
    # product cards -> card facts (not chunked), then remove them
    cards = {}
    for a in s.find_all("a", string=re.compile("Know More")):
        el = a
        while el.parent is not None:
            el = el.parent
            if el.find("h3") and "Key Highlights" in el.get_text():
                break
        ls = lines_of(el)
        if ls and ls[0] in KNOWN:
            cards[ls[0]] = ls
            el.decompose()
    faqs = faq_items(s)
    for box in s.select("div.qnas"):
        box.decompose()
    blocks = s.body.find_all("section", class_="main-content", recursive=False)
    sections, cur, unit = [], None, None
    tables, consume_after = [], False

    def start(title, kind):
        nonlocal cur, unit
        cur = dict(title=title, kind=kind, units=[])
        sections.append(cur)
        unit = dict(h3=None, lines=[])
        cur["units"].append(unit)

    start("Introduction", "intro")
    elements = [e for b in blocks for e in b.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"])]
    for el in elements:
        if el.find_parent(["table", "nav", "footer", "header"]) or (el.name == "p" and el.find_parent("li")):
            continue
        text = para(el)
        if el.name in ("h2", "h3") and re.match(r"(Go Beyond|Meet Our|Featured Videos)", text):
            break
        if el.name == "table":
            before = ""
            if unit["lines"] and not unit["lines"][-1].startswith("- "):
                before = unit["lines"].pop()
            heads, trows = table_rows(el)
            tables.append(dict(title=cur["title"], before=before, after="", body=table_text(heads, trows),
                               facts=table_facts(heads, trows)))
            consume_after = True
            continue
        if not text:
            continue
        if consume_after and el.name == "p" and len(text) > 25 and not text.startswith("Still, trying"):
            tables[-1]["after"] = text
            consume_after = False
            continue
        consume_after = False
        if el.name == "h1":
            continue
        if el.name == "h2":
            kind = "highlights_advantages" if text.startswith("Highlights and Advantages") else "explainer"
            start(text, kind)
        elif el.name == "h3" and cur["kind"] == "intro":
            start(text, "explainer")  # pages whose explainers are h3 headings straight under the hero
        elif el.name == "h3":
            unit = dict(h3=text, lines=[])
            cur["units"].append(unit)
        elif el.name == "h4":
            unit["lines"].append(text)
        elif el.name == "li":
            unit["lines"].append("- " + text)
        else:
            unit["lines"].append(text)
    return dict(category=cat, url=category_url(cat), intro=intro, sections=sections, tables=tables, cards=cards, faqs=faqs)


# ------------------------------------------------------------------ chunking
MAXC = 2000  # ~500 tokens
CHUNKS = []


def tok(t):
    return round(len(t) / 4)


def add(**kw):
    body, header = kw.pop("body"), kw.pop("header")
    text = f"{header}\n{body}".strip()
    known, legacy = mentions(text, kw.get("product"))
    kw.setdefault("region", None)
    kw.setdefault("topic", None)
    kw.setdefault("question", None)
    kw.setdefault("purchase_faq", False)
    CHUNKS.append(dict(id=kw.pop("cid"), text=text, header=header, mentions=known, legacy_mentions=legacy,
                       tokens=tok(text), **kw))


def split_sentences(text, limit):
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + len(sent) + 1 > limit:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    return parts + ([cur] if cur else [])


def pack(units, limit=MAXC):
    """Greedy-pack text units (never cutting inside a sentence)."""
    out, cur = [], ""
    for u in units:
        for piece in ([u] if len(u) <= limit else split_sentences(u, limit)):
            if cur and len(cur) + len(piece) + 1 > limit:
                out.append(cur)
                cur = piece
            else:
                cur = f"{cur}\n{piece}".strip()
    return out + ([cur] if cur else [])


def region_name(code, rec):
    return REGIONS.get(code, code)


def product_chunks(r):
    p, cats, series = r["product"], r["categories"], r["series"]
    catlabel = ", ".join(cats)

    def H(section):
        return f"[Product: {p} | Category: {catlabel} | Section: {section}]"

    base = dict(product=p, series=series, category=cats, page_type="product", url=r["url"])

    # About
    if r["about"]:
        add(cid=f"{p}:about", header=H("About"), body="\n".join(r["about"]), section="About", chunk_type="about", **base)
    # Key highlights (+ release / form factor labels live in packaging & profile)
    if r["highlights"]:
        add(cid=f"{p}:highlights", header=H("Key Highlights"), body="Key highlights: " + "; ".join(r["highlights"]),
            section="Key Highlights", chunk_type="key_highlights", **base)
    # Bands: one chunk per region (all technologies inside), else one per technology
    by_region, by_tech = {}, {}
    for e in r["bands"]:
        (by_region if e["region"] else by_tech).setdefault(e["region"] or e["tech"] or "all", []).append(e)
    for reg, es in by_region.items():
        lines = [f"- {e['tech'] or 'Bands'}: {e['bands']}" for e in es]
        if r["band_extra"] and reg == list(by_region)[0]:
            lines += [f"- {x}" for x in r["band_extra"]]
        add(cid=f"{p}:bands:{reg}", header=H(f"Bands – {region_name(reg, r)} ({reg})"),
            body=f"Cellular bands supported in region {reg} ({region_name(reg, r)}):\n" + "\n".join(lines),
            section=f"Bands – {reg}", chunk_type="bands", region=reg, **base)
    for tech, es in by_tech.items():
        body = "\n".join(f"- {e['tech'] or 'Bands'}: {e['bands']}" for e in es)
        extra = ("\n" + "\n".join(r["band_extra"])) if r["band_extra"] and tech == list(by_tech)[0] and not by_region else ""
        add(cid=f"{p}:bands:{tech}", header=H(f"Bands – {tech}"),
            body=f"Cellular bands supported ({tech}; the page lists no regional breakdown):\n{body}{extra}",
            section=f"Bands – {tech}", chunk_type="bands", **base)
    # GNSS + OS
    gnss = r["gnss"] or "not listed in this page's Technical Data"
    add(cid=f"{p}:gnss_os", header=H("GNSS and Operating System"),
        body=f"Supported location services (GNSS): {gnss}\nOperating system: {r['os'] or 'not listed'}",
        section="GNSS and OS", chunk_type="gnss_os", **base)
    # Speeds (+ fallback statements from Key Highlights)
    if r["speeds"]:
        lines = [f"- {l}: {v}" for l, v in r["speeds"]]
        fb = [h for h in r["highlights"] if "fallback" in h.lower()]
        add(cid=f"{p}:speeds", header=H("Data speeds"),
            body="Cellular connectivity peak download (DL) and uplink (UL) speeds:\n" + "\n".join(lines)
            + (f"\nFallback (Key Highlights): {', '.join(fb)}" if fb else ""),
            section="Data speeds", chunk_type="speeds", **base)
    # Packaging (+ form factors, + 3GPP release)
    pk = [f"{l}: {v}" for l, v in r["packaging"]]
    if pk or r["form_factors"]:
        body = "Packaging: " + "; ".join(pk) if pk else "Packaging:"
        if r["form_factors"]:
            body += f"\nAvailable form factor(s): {', '.join(r['form_factors'])}"
        if r["release"]:
            body += f"\n{r['release']}"
        add(cid=f"{p}:packaging", header=H("Packaging and form factors"), body=body, section="Packaging",
            chunk_type="packaging", **base)
    # Interfaces
    if r["interfaces"]:
        add(cid=f"{p}:interfaces", header=H("Interfaces"),
            body="Interfaces: " + ", ".join(r["interfaces"]) + "\n(Items marked 'optional' are optional features; "
            "items marked 'requires SDK' need the Cavli SDK.)", section="Interfaces", chunk_type="interfaces", **base)
    # Use cases
    if r["use_cases"]:
        add(cid=f"{p}:use_cases", header=H("Use Cases"), body="Use cases across IoT applications: " + "; ".join(r["use_cases"]),
            section="Use Cases", chunk_type="use_cases", **base)
    # Variants
    v = r["variants"]
    if v and v["format"] == "skus" and v["skus"]:
        lines = [f"- {s_['sku']}: " + "; ".join(f"{k} {val}" for k, val in s_["attrs"].items()) for s_ in v["skus"]]
        body = "Variants available for ordering samples:\n" + "\n".join(lines)
        if v["regional"]:
            body += "\nRegional codes: " + "; ".join(v["regional"])
        if v["variant_codes"]:
            body += "\nVariant codes: " + "; ".join(v["variant_codes"])
        if v["note"]:
            body += f"\nNote: {v['note']}"
        add(cid=f"{p}:variants", header=H("Variants"), body=body, section="Variants", chunk_type="variants", **base)
    elif v and v["format"] == "decoder":
        lines = [f"- {row['param']} ({row['options']}): " + "; ".join(row["decoded"]) if row["decoded"]
                 else f"- {row['param']}: {row['options']}" for row in v["rows"]]
        add(cid=f"{p}:variants", header=H("Variants (part-number decoder)"),
            body="Variant options (part-number decoder for ordering):\n" + "\n".join(lines), section="Variants",
            chunk_type="variants", **base)
    # FAQ: one chunk per question
    for i, f in enumerate(r["faqs"], 1):
        t = topic_of(f["question"], f["answer"])
        add(cid=f"{p}:faq:{i}", header=H(f"FAQ – {t}"), body=f"Q: {f['question']}\nA: {f['answer']}",
            section="FAQ", chunk_type="faq", topic=t, question=f["question"], purchase_faq=(t == "purchase"), **base)


def category_chunks(c):
    cat = c["category"]
    base = dict(product=None, series=None, category=[cat], page_type="category", url=c["url"])

    def H(section):
        return f"[Category: {cat} | Page: category overview | Section: {section}]"

    n = Counter()

    def cid(kind):
        n[kind] += 1
        return f"{CAT_SLUG[cat]}:{kind}:{n[kind]}"

    if c["intro"]:
        add(cid=cid("intro"), header=H("Introduction"), body="\n".join(c["intro"]), section="Introduction",
            chunk_type="intro", **base)
    for sec in c["sections"]:
        if sec["kind"] == "intro" and not any(u["lines"] for u in sec["units"]):
            continue
        units = []
        for u in sec["units"]:
            body = "\n".join(u["lines"])
            if body.strip():
                units.append((f"{u['h3']}\n" if u["h3"] else "") + body)
        if not units:
            continue
        kind = {"intro": "explainer", "explainer": "explainer", "highlights_advantages": "highlights_advantages"}[sec["kind"]]
        title = sec["title"][:140]
        for part in pack(units):
            add(cid=cid(kind), header=H(title), body=part,
                section=title, chunk_type=kind, **base)
    for t in c["tables"]:
        body = "\n".join(x for x in [t["before"], t["body"], t["after"]] if x)
        add(cid=cid("table"), header=H(f"Comparison table – {t['title'][:100]}"), body=body,
            section=f"Comparison table – {t['title'][:100]}", chunk_type="table", **base)
    for i, f in enumerate(c["faqs"], 1):
        t = topic_of(f["question"], f["answer"])
        add(cid=f"{CAT_SLUG[cat]}:faq:{i}", header=H(f"FAQ – {t}"), body=f"Q: {f['question']}\nA: {f['answer']}",
            section="FAQ", chunk_type="faq", topic=t, question=f["question"], purchase_faq=(t == "purchase"), **base)


# ------------------------------------------------------------------ orchestration
def build(refresh=False):
    CHUNKS.clear()
    NORMALIZATIONS.clear()
    products, categories = {}, {}
    for name in PRODUCTS:
        products[name] = parse_product(name, fetch(PRODUCTS[name][2], product_url(name), refresh))
    for slug, (name, path) in CATEGORIES.items():
        categories[name] = parse_category(name, fetch(slug, f"{BASE}/{path}", refresh))
    for r in products.values():
        product_chunks(r)
    for c in categories.values():
        category_chunks(c)
    return products, categories


def write_json(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def report():
    by = Counter(c["chunk_type"] for c in CHUNKS)
    toks = sorted(c["tokens"] for c in CHUNKS)
    print(f"{len(CHUNKS)} chunks | tokens min {toks[0]} median {toks[len(toks)//2]} max {toks[-1]}")
    print(dict(by))
