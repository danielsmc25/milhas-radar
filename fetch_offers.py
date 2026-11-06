
#!/usr/bin/env python3
"""Radar de Milhas: coleta ofertas de milhas e passagens em feeds RSS,
gera docs/index.html e envia alertas no Telegram. Sem dependências externas."""

import html
import json
import os
import re
import urllib.parse
import urllib.request
import zlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

FEEDS = {
    "Passageiro de Primeira": "https://passageirodeprimeira.com/feed/",
    "Melhores Cartões": "https://www.melhorescartoes.com.br/feed",
    "Melhores Destinos": "https://www.melhoresdestinos.com.br/feed",
}

if os.environ.get("FEEDS"):
    FEEDS = dict(p.split("=", 1) for p in os.environ["FEEDS"].split(","))

DAYS = 3
DESTAQUE_HORAS = 36
STATE = "alertas_enviados.json"

# ---------- Milhas ----------

BUY = re.compile("|".join([
    r"compr(a|ar|e|ando)\s+(de\s+)?(até\s+)?[\d\.]*\s*(mil\s+)?(milhas|pontos)",
    r"milheiro",
    r"transfer[êe]ncias?\s+bonificadas?",
    r"b[ôo]nus.{0,40}transfer[êe]ncia",
    r"\d+%\s+de\s+desconto.{0,30}(compra|milhas|pontos)",
    r"clube.{0,40}b[ôo]nus",
]), re.I)

PRODUCT = re.compile(
    r"(iphone|celular|smartphone|notebook|geladeira|seguro|aluguel de carro|hotel|hotéis|hospedagem)",
    re.I
)

PROGRAMS = {
    "Smiles": ["smiles"],
    "LATAM Pass": ["latam pass", "latampass", "latam"],
    "Azul Fidelidade": ["azul fidelidade", "tudoazul", "pontos azul", "milhas azul", "azul"],
    "Livelo": ["livelo"],
    "Esfera": ["esfera"],
    "Iupp": ["iupp"],
    "Flying Blue": ["flying blue"],
    "MileagePlus": ["mileageplus"],
    "AAdvantage": ["aadvantage"],
    "Avios": ["avios", "iberia", "british airways"],
    "TAP Miles&Go": ["tap miles", "miles&go"],
    "LifeMiles": ["lifemiles", "avianca"],
    "ConnectMiles": ["connectmiles", "copa"],
    "Aeroplan": ["aeroplan", "air canada"],
    "SkyMiles": ["skymiles", "delta"],
    "Miles & More": ["miles & more", "miles&more", "lufthansa"],
    "Emirates Skywards": ["skywards", "emirates"],
    "Qatar Privilege Club": ["privilege club", "qatar"],
    "Turkish Miles&Smiles": ["miles&smiles", "turkish"],
    "Aerolíneas Plus": ["aerolíneas", "aerolineas"],
    "Hilton Honors": ["hilton"],
}

# ---------- Passagens ----------

FARE = re.compile(
    r"(passagens?|voos?|trechos?|ida e volta|ida\+volta|emiss(ão|ões|ao))",
    re.I
)

DEAL = re.compile(
    r"(R\$\s?\d|desconto|promo|\boff\b|barat|cupom|imperd|relâmpago|liquida|black)",
    re.I
)

AIRLINES = {
    "Azul": ["azul"],
    "LATAM": ["latam"],
    "GOL": ["gol"],
    "TAP": ["tap"],
    "Copa": ["copa airlines", "copa"],
    "Avianca": ["avianca"],
    "Air France / KLM": ["air france", "klm"],
    "Iberia": ["iberia"],
    "British Airways": ["british airways"],
    "Lufthansa": ["lufthansa"],
    "American": ["american airlines", "american"],
    "United": ["united"],
    "Delta": ["delta"],
    "Air Canada": ["air canada"],
    "Emirates": ["emirates"],
    "Qatar": ["qatar"],
    "Turkish": ["turkish"],
    "Aerolíneas Argentinas": ["aerolíneas", "aerolineas"],
    "Aeroméxico": ["aeroméxico", "aeromexico"],
    "ITA Airways": ["ita airways"],
    "Sky": ["sky airline"],
    "JetSMART": ["jetsmart"],
    "Flybondi": ["flybondi"],
    "Voepass": ["voepass"],
}

UA = {"User-Agent": "milhas-radar/4.0 (+leitor de RSS pessoal)"}
NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{1,2})?)"


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def parse(source, xml_bytes):
    for it in ET.fromstring(xml_bytes).iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()

        try:
            when = parsedate_to_datetime(it.findtext("pubDate"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if title and link:
            yield {
                "source": source,
                "title": title,
                "link": link,
                "date": when,
            }


def money(s):
    return float(s.replace(".", "").replace(",", "."))


def find_entity(title, table, default="Outros"):
    low = title.lower()
    parts = re.split(r"\spara\s", low, maxsplit=1)

    for text in ([parts[1], low] if len(parts) == 2 else [low]):
        best = None

        for name, aliases in table.items():
            for a in aliases:
                m = re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text)
                if m and (best is None or m.start() < best[0]):
                    best = (m.start(), name)

        if best:
            return best[1]

    return default


def find_cpm(t):
    m = (
        re.search(r"milheiro.{0,40}?R\$\s?" + NUM, t, re.I)
        or re.search(r"R\$\s?" + NUM + r"[^.]{0,25}milheiro", t, re.I)
    )
    return money(m.group(1)) if m else None


def find_fare(t):
    m = re.search(
        r"(?<!\w)(?:a partir de|por apenas|por|apenas|só|a)\s+R\$\s?" + NUM,
        t,
        re.I,
    )
    return money(m.group(1)) if m else None


def find_discount(t):
    m = (
        re.search(
            r"R\$\s?" + NUM + r"\s*(?:de\s+)?(?:off|desconto)",
            t,
            re.I,
        )
        or re.search(
            r"(?:cupom|desconto)\s+de\s+(?:até\s+)?R\$\s?" + NUM,
            t,
            re.I,
        )
    )
    return money(m.group(1)) if m else None


def milhas_kind(t):
    if re.search(r"clube", t, re.I):
        return "Assinatura de clube"
    if re.search(r"transfer", t, re.I):
        return "Transferência bonificada"
    if re.search(r"compr|milheiro", t, re.I):
        return "Compra"
    return "Oferta"


def classify(o):
    t = o["title"]

    if PRODUCT.search(t) and not BUY.search(t):
        return None

    if re.search(r"iphone|celular|smartphone|notebook|geladeira", t, re.I):
        return None

    pct = re.search(r"(\d{2,3})\s?%", t)
    o["percent"] = pct.group(1) + "%" if pct else ""

    if BUY.search(t):
        o.update(
            cat="milhas",
            entity=find_entity(t, PROGRAMS),
            kind=milhas_kind(t),
            cpm=find_cpm(t),
            fare=None,
            discount=None,
        )
        return o

    if FARE.search(t) and DEAL.search(t):
        with_points = bool(
            re.search(r"milhas|pontos|emiss|resgate", t, re.I)
        )

        ent = find_entity(t, AIRLINES, default="") or find_entity(
            t, PROGRAMS, default="Outras companhias"
        )

        o.update(
            cat="passagem",
            entity=ent,
            kind="Com milhas ou pontos" if with_points else "Em dinheiro",
            cpm=None,
            fare=find_fare(t),
            discount=find_discount(t),
        )
        return o

    return None


def brl(v):
    s = f"{v:,.2f}" if v % 1 else f"{v:,.0f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


# ---------- Alertas (Telegram) ----------

def telegram(token, chat, text):
    base = os.environ.get("TELEGRAM_API", "https://api.telegram.org")
    data = urllib.parse.urlencode({
        "chat_id": chat,
        "text": text,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{base}/bot{token}/sendMessage",
            data=data,
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            response.read()
        return True

    except Exception as e:
        print(f"Aviso: falha ao enviar alerta: {e}")
        return False


def alerts(offers):
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

    if not token or not chat:
        print("Aviso: TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configurado.")
        return

    # Teste manual do grupo, sem alterar o histórico de alertas.
    if os.environ.get("TESTE_TELEGRAM") == "1":
        ok = telegram(
            token,
            chat,
            "✈️ Radar de Milhas — TESTE\n"
            "✅ Mensagem enviada ao grupo com sucesso!\n"
            "📢 Este grupo receberá novas promoções.",
        )

        if not ok:
            raise RuntimeError("Falha no teste do Telegram")

        print("Teste do Telegram enviado com sucesso.")
        return

    lim_m = float(os.environ.get("ALERTA_MILHEIRO") or 18)
    lim_p = float(os.environ.get("ALERTA_PASSAGEM") or 400)

    hot = offers
    

    first_run = not os.path.exists(STATE)

    if first_run:
        sent = []
    else:
        with open(STATE, encoding="utf-8") as f:
            sent = json.load(f)

       if first_run:
        print("Primeira execução: enviando ofertas encontradas.")
        sent = []

        for o in hot:
            msg = (
                f"🔔 {o['entity']}\n"
                f"{o['title']}\n"
                f"{o['link']}"
            )

            if telegram(token, chat, msg):
                sent.append(o["link"])

    else:
        novos = [o for o in hot if o["link"] not in sent]

        for o in novos:
            if o["cat"] == "milhas":
                val = f"milheiro {brl(o['cpm'])}"
            else:
                val = f"passagem a partir de {brl(o['fare'])}"

            msg = (
                f"🔔 {o['entity']}: {val}\n"
                f"{o['title']}\n"
                f"{o['link']}"
            )

            if telegram(token, chat, msg):
                sent.append(o["link"])

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(sent[-500:], f, ensure_ascii=False)


# ---------- Página ----------

def hue(name):
    return zlib.crc32(name.encode()) % 360


def when_label(o, now):
    d = o["date"].astimezone(now.tzinfo)
    delta = (now.date() - d.date()).days

    return (
        "hoje " if delta == 0
        else "ontem " if delta == 1
        else f"{d:%d/%m} "
    ) + f"{d:%H:%M}"


def pick(offers, valfn, reverse, now, n=3):
    cands = [o for o in offers if valfn(o) is not None]

    if reverse:
        return sorted(
            cands,
            key=lambda o: (valfn(o), -o["date"].timestamp()),
            reverse=True,
        )[:n]

    return sorted(
        cands,
        key=lambda o: (valfn(o), -o["date"].timestamp()),
    )[:n]


def card(o, rank, big, unit, now):
    return (
        f'<a class="hl" style="--c:hsl({hue(o["entity"])} 70% 48%)" '
        f'href="{html.escape(o["link"])}" rel="noopener">'
        f'<span class="rank">{rank}º</span>'
        f'<span class="big">{big}</span>'
        f'<span class="unit">{unit}</span>'
        f'<b>{html.escape(o["entity"])}</b>'
        f'<span class="hmeta">{html.escape(o["kind"])} '
        f'· {when_label(o, now)}</span>'
        f'<span class="go">Ver oferta →</span></a>'
    )


def highlights(milhas, passagens, now):
    m = pick(milhas, lambda o: o["cpm"], False, now)
    p = pick(passagens, lambda o: o["fare"], False, now)

    def block(title, cards):
        body = "".join(cards) or (
            '<p class="vazio">'
            'Nenhuma oferta com preço identificado nos últimos dias.'
            '</p>'
        )
        return (
            f'<div class="hgroup"><h2>{title}</h2>'
            f'<div class="hgrid">{body}</div></div>'
        )

    mc = [
        card(o, i + 1, brl(o["cpm"]), "por milheiro", now)
        for i, o in enumerate(m)
    ]

    pc = [
        card(o, i + 1, brl(o["fare"]), "a partir de", now)
        for i, o in enumerate(p)
    ]

    return block("Menores milheiros", mc) + block("Melhores passagens", pc)


def render_section(cat, offers, now, label_best):
    progs = {}

    for o in offers:
        progs[o["entity"]] = progs.get(o["entity"], 0) + 1

    chips = (
        '<button class="chip" data-p="all" aria-pressed="true">'
        f'Todos ({len(offers)})</button>'
    )

    for p, n in sorted(
        progs.items(),
        key=lambda x: (x[0].startswith("Outr"), x[0]),
    ):
        chips += (
            f'<button class="chip" '
            f'style="--c:hsl({hue(p)} 70% 48%)" '
            f'data-p="{html.escape(p)}" aria-pressed="false">'
            f'<i></i>{html.escape(p)} ({n})</button>'
        )

    key = "cpm" if cat == "milhas" else "fare"
    first = next(
        (i for i, o in enumerate(offers) if o[key] is not None),
        None,
    )

    items = []

    for i, o in enumerate(offers):
        tags = []

        if i == first:
            tags.append(f'<span class="best">{label_best}</span>')

        if o["cpm"] is not None:
            tags.append(f'<span>milheiro {brl(o["cpm"])}</span>')

        if o["fare"] is not None:
            tags.append(f'<span>a partir de {brl(o["fare"])}</span>')

        if o["discount"] is not None:
            tags.append(f'<span>desconto de {brl(o["discount"])}</span>')

        if o["percent"]:
            tags.append(f'<span>{o["percent"]}</span>')

        tags.append(f'<span class="k">{html.escape(o["kind"])}</span>')

        items.append(
            f'<li style="--c:hsl({hue(o["entity"])} 70% 48%)" '
            f'data-p="{html.escape(o["entity"])}">'
            f'<div class="meta"><b>{html.escape(o["entity"])}</b>'
            f' · {when_label(o, now)}'
            f' · {html.escape(o["source"])}</div>'
            f'<a href="{html.escape(o["link"])}" rel="noopener">'
            f'{html.escape(o["title"])}</a>'
            f'<div class="tags">{"".join(tags)}</div></li>'
        )

    rows = "".join(items) or "<li>Nada encontrado nos últimos dias.</li>"

    return (
        f'<div class="chips" role="group" aria-label="Filtrar">'
        f'{chips}</div><ul>{rows}</ul>'
    )


def render(milhas, passagens, now):
    tabs = (
        '<button class="tab" data-s="milhas" aria-pressed="true">'
        f'Comprar milhas <em>{len(milhas)}</em></button>'
        '<button class="tab" data-s="passagem" aria-pressed="false">'
        f'Passagens em promoção <em>{len(passagens)}</em></button>'
    )

    secs = (
        '<section class="sec" data-s="milhas">'
        '<p class="sub">Compra de milhas e pontos, transferências '
        'bonificadas e clubes, do menor para o maior valor do milheiro.</p>'
        f'{render_section("milhas", milhas, now, "Menor milheiro")}'
        '</section>'
        '<section class="sec" data-s="passagem" hidden>'
        '<p class="sub">Passagens e voos com desconto, dos menores preços '
        'aos maiores. Ofertas sem preço no título vêm depois.</p>'
        f'{render_section("passagem", passagens, now, "Menor preço")}'
        '</section>'
    )

    return (
        TEMPLATE
        .replace("{{HL}}", highlights(milhas, passagens, now))
        .replace("{{TABS}}", tabs)
        .replace("{{SECS}}", secs)
        .replace("{{UPDATED}}", f"{now:%d/%m/%Y às %H:%M}")
        .replace("{{DAYS}}", str(DAYS))
    )


def main():
    since = datetime.now(timezone.utc) - timedelta(days=DAYS)
    seen = set()
    offers = []

    for name, url in FEEDS.items():
        try:
            items = list(parse(name, fetch(url)))
        except Exception as e:
            print(f"Aviso: falha em {name}: {e}")
            continue

        for o in items:
            if o["date"] < since or o["link"] in seen:
                continue

            c = classify(o)

            if c:
                seen.add(o["link"])
                offers.append(c)

    milhas = sorted(
        [o for o in offers if o["cat"] == "milhas"],
        key=lambda o: (
            o["cpm"] is None,
            o["cpm"] or 0,
            -o["date"].timestamp(),
        ),
    )

    passagens = sorted(
        [o for o in offers if o["cat"] == "passagem"],
        key=lambda o: (
            o["fare"] is None,
            o["fare"] or 0,
            -o["date"].timestamp(),
        ),
    )

    now = datetime.now(timezone(timedelta(hours=-3)))

    os.makedirs("docs", exist_ok=True)

    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(
            [
                {**o, "date": o["date"].isoformat()}
                for o in milhas + passagens
            ],
            f,
            ensure_ascii=False,
            indent=1,
        )

    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(render(milhas, passagens, now))

    alerts(milhas + passagens)

    print(
        f"{len(milhas)} ofertas de milhas e "
        f"{len(passagens)} de passagens gravadas."
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Radar de Milhas — milhas e passagens em promoção</title>
<meta name="description" content="Menores milheiros e passagens em promoção, atualizados a cada 15 minutos.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='15' fill='%230B2A4A'/%3E%3Ccircle cx='16' cy='16' r='9' fill='none' stroke='%23FFA62B' stroke-width='2'/%3E%3Ccircle cx='22' cy='10' r='3' fill='%23FFA62B'/%3E%3C/svg%3E">
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@600;800&family=Figtree:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#F3F7FB;--ink:#0B1F36;--mut:#52667C;--card:#fff;--line:#D5E0EB;--acc:#FF8A00;--good:#0B8A55;--chip:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#07121F;--ink:#EAF2FA;--mut:#9DB2C7;--card:#0E2236;--line:#22405E;--acc:#FFA62B;--good:#46D39A;--chip:#0E2236}}
[hidden]{display:none!important}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 Figtree,system-ui,sans-serif}
h1,h2,.big,.rank{font-family:"Bricolage Grotesque",Figtree,system-ui,sans-serif}
.hero{background:linear-gradient(135deg,#0B2A4A,#0F4C81 55%,#1B8CB5);color:#fff;position:relative;overflow:hidden}
.hero .in{max-width:900px;margin:0 auto;padding:34px 20px 40px;position:relative;z-index:1}
.brand{display:flex;align-items:center;gap:12px}
.radar{width:46px;height:46px;border-radius:50%;border:2px solid rgba(255,255,255,.55);position:relative;flex:none;background:radial-gradient(circle,transparent 30%,rgba(255,255,255,.25) 31%,transparent 33%,transparent 60%,rgba(255,255,255,.2) 61%,transparent 63%)}
.radar::before{content:"";position:absolute;inset:0;border-radius:50%;background:conic-gradient(from 0deg,rgba(255,166,43,.85),transparent 28%);animation:giro 3.5s linear infinite}
.radar::after{content:"";position:absolute;width:8px;height:8px;border-radius:50%;background:#FFA62B;top:9px;right:8px;box-shadow:0 0 8px #FFA62B}
@keyframes giro{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.radar::before{animation:none}.live i{animation:none}}
h1{font-size:clamp(30px,6vw,46px);margin:0;font-weight:800;letter-spacing:-.02em}
.tag{margin:12px 0 0;color:#D6E8F7;max-width:56ch}
.live{display:inline-flex;align-items:center;gap:8px;margin-top:16px;font-size:14px;background:rgba(255,255,255,.14);padding:5px 12px;border-radius:99px}
.live i{width:9px;height:9px;border-radius:50%;background:#46D39A;animation:pisca 1.6s infinite}
@keyframes pisca{50%{opacity:.25}}
main{max-width:900px;margin:0 auto;padding:26px 20px 60px}
.novo{background:var(--acc);color:#0B1F36;border-radius:12px;padding:10px 14px;margin:0 0 18px;font-weight:600}
.novo button{font:inherit;margin-left:8px;padding:3px 12px;border-radius:8px;border:2px solid #0B1F36;background:#fff;color:#0B1F36;cursor:pointer}
.hgroup{margin:0 0 26px}
.hgroup h2{font-size:22px;margin:0 0 12px}
.hgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}
.hl{display:flex;flex-direction:column;gap:2px;text-decoration:none;color:var(--ink);background:var(--card);border:1px solid var(--line);border-top:5px solid var(--c);border-radius:16px;padding:14px 16px;transition:transform .15s,box-shadow .15s}
.hl:hover,.hl:focus-visible{transform:translateY(-3px);box-shadow:0 8px 22px rgba(11,31,54,.18)}
.rank{font-size:13px;font-weight:600;color:var(--mut)}
.big{font-size:34px;font-weight:800;line-height:1.05;color:var(--ink)}
.unit{font-size:13px;color:var(--mut);margin-bottom:6px}
.hmeta{font-size:13px;color:var(--mut)}
.go{margin-top:8px;font-size:14px;font-weight:600;color:var(--c)}
.vazio{color:var(--mut);margin:0}
.tabs{display:flex;gap:8px;margin:8px 0 18px;flex-wrap:wrap}
.tab{font:inherit;font-weight:600;padding:9px 16px;border-radius:12px;border:2px solid var(--ink);background:transparent;color:var(--ink);cursor:pointer}
.tab em{font-style:normal;font-size:13px;margin-left:6px;padding:1px 8px;border-radius:99px;background:var(--line);color:var(--ink)}
.tab[aria-pressed=true]{background:var(--ink);color:var(--bg)}
.tab[aria-pressed=true] em{background:var(--acc);color:#0B1F36}
.sub{color:var(--mut);margin:0 0 14px;font-size:16px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}
.chip{font:inherit;font-size:14px;padding:5px 12px;border-radius:99px;border:1.5px solid var(--line);background:var(--chip);color:var(--ink);cursor:pointer;display:inline-flex;align-items:center;gap:6px}
.chip i{width:9px;height:9px;border-radius:50%;background:var(--c)}
.chip[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
a:focus-visible,.chip:focus-visible,.tab:focus-visible,.novo button:focus-visible{outline:3px solid var(--acc);outline-offset:2px}
ul{list-style:none;padding:0;margin:0}
li{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c);border-radius:14px;padding:14px 16px;margin-bottom:12px}
li a{color:var(--ink);font-weight:600;text-decoration:none}
li a:hover{text-decoration:underline}
.meta{font-size:14px;color:var(--mut)}
.meta b{color:var(--c)}
.tags span{display:inline-block;margin:8px 8px 0 0;padding:2px 10px;border-radius:99px;background:var(--acc);color:#0B1F36;font-size:14px;font-weight:600}
.tags .k{background:transparent;color:var(--mut);border:1px solid var(--line);font-weight:500}
.tags .best{background:var(--good);color:#fff}
footer{color:var(--mut);font-size:14px;margin-top:30px}
</style>
</head>
<body>
<header class="hero">
<div class="in">
<div class="brand">
<div class="radar" aria-hidden="true"></div>
<h1>Radar de Milhas</h1>
</div>
<p class="tag">Os menores milheiros e as passagens em promoção, direto das fontes do setor, num só lugar.</p>
<span class="live"><i></i>Última mudança na lista: {{UPDATED}} · busca a cada 15 min</span>
</div>
</header>
<main>
<div id="novo" class="novo" hidden>
Há novidades.
<button id="recarregar">Atualizar a página</button>
</div>
{{HL}}
<div class="tabs" role="group" aria-label="Escolher lista">
{{TABS}}
</div>
{{SECS}}
<footer>
Lista montada automaticamente a partir dos títulos de blogs do setor;
cada item leva à matéria original. Preços e valores só aparecem quando
estão no título. Mostramos ofertas dos últimos {{DAYS}} dias.
Confira prazo, regras e disponibilidade no site da companhia
ou do programa antes de comprar.
</footer>
</main>
<script>
function wire(sec){
  var chips=sec.querySelectorAll('.chip');
  var items=sec.querySelectorAll('li[data-p]');
  chips.forEach(function(c){
    c.addEventListener('click',function(){
      chips.forEach(function(x){
        x.setAttribute('aria-pressed','false');
      });
      c.setAttribute('aria-pressed','true');
      items.forEach(function(i){
        i.hidden=c.dataset.p!=='all'&&i.dataset.p!==c.dataset.p;
      });
    });
  });
}
var secs=document.querySelectorAll('.sec');
var tabs=document.querySelectorAll('.tab');
secs.forEach(wire);
tabs.forEach(function(t){
  t.addEventListener('click',function(){
    tabs.forEach(function(x){
      x.setAttribute('aria-pressed','false');
    });
    t.setAttribute('aria-pressed','true');
    secs.forEach(function(s){
      s.hidden=s.dataset.s!==t.dataset.s;
    });
  });
});
var base=null;
function checar(){
  fetch(location.href,{cache:'no-store'})
    .then(function(r){return r.text();})
    .then(function(t){
      if(base===null){
        base=t;
      }else if(t!==base){
        document.getElementById('novo').hidden=false;
      }
    })
    .catch(function(){});
}
document.getElementById('recarregar').addEventListener(
  'click',
  function(){location.reload();}
);
checar();
setInterval(checar,300000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
