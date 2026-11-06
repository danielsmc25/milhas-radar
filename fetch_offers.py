#!/usr/bin/env python3
"""Radar de Milhas: coleta, em feeds RSS, ofertas de compra de milhas/pontos e passagens em promoção
e gera docs/index.html. Sem dependências externas. Cada oferta leva à matéria original."""
import html, json, os, re, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

FEEDS = {
    "Passageiro de Primeira": "https://passageirodeprimeira.com/feed/",
    "Melhores Cartões": "https://www.melhorescartoes.com.br/feed",
    "Melhores Destinos": "https://www.melhoresdestinos.com.br/feed",
}
if os.environ.get("FEEDS"):  # para testes: "Nome=url,Nome2=url2"
    FEEDS = dict(p.split("=", 1) for p in os.environ["FEEDS"].split(","))

DAYS = 3  # promoções duram pouco; aumente se quiser mais histórico

# ---------- Aba 1: compra de milhas ----------
BUY = re.compile("|".join([
    r"compr(a|ar|e|ando)\s+(de\s+)?(até\s+)?[\d\.]*\s*(mil\s+)?(milhas|pontos)",
    r"milheiro",
    r"transfer[êe]ncias?\s+bonificadas?",
    r"b[ôo]nus.{0,40}transfer[êe]ncia",
    r"\d+%\s+de\s+desconto.{0,30}(compra|milhas|pontos)",
    r"clube.{0,40}b[ôo]nus",
]), re.I)
NOT_PRODUCT = re.compile(r"(iphone|celular|smartphone|notebook|geladeira|seguro|aluguel de carro|hotel|hotéis|hospedagem)", re.I)

PROGRAMS = {  # programa -> variações nos títulos
    "Smiles": ["smiles"],
    "LATAM Pass": ["latam pass", "latampass", "latam"],
    "Azul Fidelidade": ["azul fidelidade", "tudoazul", "pontos azul", "milhas azul", "azul"],
    "Livelo": ["livelo"], "Esfera": ["esfera"], "Iupp": ["iupp"],
    "Flying Blue": ["flying blue"], "MileagePlus": ["mileageplus"], "AAdvantage": ["aadvantage"],
    "Avios": ["avios", "iberia", "british airways"], "TAP Miles&Go": ["tap miles", "miles&go"],
    "LifeMiles": ["lifemiles", "avianca"], "ConnectMiles": ["connectmiles", "copa"],
    "Aeroplan": ["aeroplan", "air canada"], "SkyMiles": ["skymiles", "delta"],
    "Miles & More": ["miles & more", "miles&more", "lufthansa"],
    "Emirates Skywards": ["skywards", "emirates"], "Qatar Privilege Club": ["privilege club", "qatar"],
    "Turkish Miles&Smiles": ["miles&smiles", "turkish"], "Aerolíneas Plus": ["aerolíneas", "aerolineas"],
    "Hilton Honors": ["hilton"],
}

# ---------- Aba 2: passagens em promoção ----------
FARE = re.compile(r"(passagens?|voos?|trechos?|ida e volta|ida\+volta|emiss(ão|ões|ao))", re.I)
DEAL = re.compile(r"(R\$\s?\d|desconto|promo|\boff\b|barat|cupom|imperd|relâmpago|liquida|black)", re.I)
AIRLINES = {
    "Azul": ["azul"], "LATAM": ["latam"], "GOL": ["gol"], "TAP": ["tap"], "Copa": ["copa airlines", "copa"],
    "Avianca": ["avianca"], "Air France / KLM": ["air france", "klm"], "Iberia": ["iberia"],
    "British Airways": ["british airways"], "Lufthansa": ["lufthansa"], "American": ["american airlines", "american"],
    "United": ["united"], "Delta": ["delta"], "Air Canada": ["air canada"], "Emirates": ["emirates"],
    "Qatar": ["qatar"], "Turkish": ["turkish"], "Aerolíneas Argentinas": ["aerolíneas", "aerolineas"],
    "Aeroméxico": ["aeroméxico", "aeromexico"], "ITA Airways": ["ita airways"], "Sky": ["sky airline"],
    "JetSMART": ["jetsmart"], "Flybondi": ["flybondi"], "Voepass": ["voepass"],
}
UA = {"User-Agent": "milhas-radar/3.0 (+leitor de RSS pessoal)"}
NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{1,2})?)"

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
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
            yield {"source": source, "title": title, "link": link, "date": when}

def money(s):
    return float(s.replace(".", "").replace(",", "."))

def find_entity(title, table, default="Outros"):
    """Acha a empresa mais citada. Em 'X para Y' vale o destino (Y)."""
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
    m = re.search(r"milheiro.{0,40}?R\$\s?" + NUM, t, re.I) or re.search(r"R\$\s?" + NUM + r"[^.]{0,25}milheiro", t, re.I)
    return money(m.group(1)) if m else None

def find_fare(t):
    m = re.search(r"(?<!\w)(?:a partir de|por apenas|por|apenas|só|a)\s+R\$\s?" + NUM, t, re.I)
    return money(m.group(1)) if m else None

def find_discount(t):
    m = re.search(r"R\$\s?" + NUM + r"\s*(?:de\s+)?(?:off|desconto)", t, re.I) or \
        re.search(r"(?:cupom|desconto)\s+de\s+(?:até\s+)?R\$\s?" + NUM, t, re.I)
    return money(m.group(1)) if m else None

def milhas_kind(t):
    if re.search(r"clube", t, re.I): return "Assinatura de clube"
    if re.search(r"transfer", t, re.I): return "Transferência bonificada"
    if re.search(r"compr|milheiro", t, re.I): return "Compra"
    return "Oferta"

def classify(o):
    t = o["title"]
    if NOT_PRODUCT.search(t) and not BUY.search(t):
        return None
    pct = re.search(r"(\d{2,3})\s?%", t)
    o["percent"] = pct.group(1) + "%" if pct else ""
    if BUY.search(t) and not re.search(r"iphone|celular|smartphone|notebook|geladeira", t, re.I):
        o.update(cat="milhas", entity=find_entity(t, PROGRAMS), kind=milhas_kind(t),
                 cpm=find_cpm(t), fare=None, discount=None)
        return o
    if FARE.search(t) and DEAL.search(t) and not re.search(r"iphone|celular|smartphone|notebook|geladeira", t, re.I):
        with_points = bool(re.search(r"milhas|pontos|emiss|resgate", t, re.I))
        ent = find_entity(t, AIRLINES, default="")
        if not ent:
            ent = find_entity(t, PROGRAMS, default="Outras companhias")
        o.update(cat="passagem", entity=ent, kind="Com milhas ou pontos" if with_points else "Em dinheiro",
                 cpm=None, fare=find_fare(t), discount=find_discount(t))
        return o
    return None

def brl(v):
    return "R$ " + (f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v % 1 else f"{v:,.0f}".replace(",", "."))

def render_section(cat, offers, now, label_best):
    progs = {}
    for o in offers:
        progs[o["entity"]] = progs.get(o["entity"], 0) + 1
    chips = '<button class="chip" data-p="all" aria-pressed="true">Todos (%d)</button>' % len(offers) + "".join(
        f'<button class="chip" data-p="{html.escape(p)}" aria-pressed="false">{html.escape(p)} ({n})</button>'
        for p, n in sorted(progs.items(), key=lambda x: (x[0].startswith("Outr"), x[0])))
    key = "cpm" if cat == "milhas" else "fare"
    first = next((i for i, o in enumerate(offers) if o[key] is not None), None)
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
            f'<li data-p="{html.escape(o["entity"])}"><div class="meta"><b>{html.escape(o["entity"])}</b>'
            f' · {o["date"].astimezone(now.tzinfo):%d/%m %H:%M} · {html.escape(o["source"])}</div>'
            f'<a href="{html.escape(o["link"])}" rel="noopener">{html.escape(o["title"])}</a>'
            f'<div class="tags">{"".join(tags)}</div></li>')
    rows = "".join(items) or "<li>Nada encontrado nos últimos dias.</li>"
    return f'<div class="chips" role="group" aria-label="Filtrar">{chips}</div><ul>{rows}</ul>'

def render(milhas, passagens, now):
    tabs = (f'<button class="tab" data-s="milhas" aria-pressed="true">Comprar milhas ({len(milhas)})</button>'
            f'<button class="tab" data-s="passagem" aria-pressed="false">Passagens em promoção ({len(passagens)})</button>')
    secs = (f'<section class="sec" data-s="milhas"><p class="sub">Compra de milhas e pontos, transferências bonificadas e clubes, do menor para o maior valor do milheiro.</p>'
            f'{render_section("milhas", milhas, now, "Menor milheiro")}</section>'
            f'<section class="sec" data-s="passagem" hidden><p class="sub">Passagens e voos com desconto, dos menores preços aos maiores. Ofertas sem preço no título vêm depois.</p>'
            f'{render_section("passagem", passagens, now, "Menor preço")}</section>')
    return (TEMPLATE.replace("{{TABS}}", tabs).replace("{{SECS}}", secs)
            .replace("{{UPDATED}}", f"{now:%d/%m/%Y às %H:%M}").replace("{{DAYS}}", str(DAYS)))

def main():
    since = datetime.now(timezone.utc) - timedelta(days=DAYS)
    seen, offers = set(), []
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
    milhas = sorted([o for o in offers if o["cat"] == "milhas"],
                    key=lambda o: (o["cpm"] is None, o["cpm"] or 0, -o["date"].timestamp()))
    passagens = sorted([o for o in offers if o["cat"] == "passagem"],
                       key=lambda o: (o["fare"] is None, o["fare"] or 0, -o["date"].timestamp()))
    now = datetime.now(timezone(timedelta(hours=-3)))
    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump([{**o, "date": o["date"].isoformat()} for o in milhas + passagens], f, ensure_ascii=False, indent=1)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(render(milhas, passagens, now))
    print(f"{len(milhas)} ofertas de milhas e {len(passagens)} de passagens gravadas.")

TEMPLATE = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Radar de Milhas — milhas e passagens em promoção</title>
<style>:root{--bg:#F6F9FC;--ink:#0E2740;--mut:#4D6178;--card:#fff;--line:#D3DEE9;--acc:#FFB81C;--good:#0B7A4B}
@media(prefers-color-scheme:dark){:root{--bg:#0A1827;--ink:#EAF2FA;--mut:#9DB2C7;--card:#112338;--line:#25405C;--good:#4FD39A}}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 system-ui,sans-serif}
main{max-width:780px;margin:0 auto;padding:28px 20px 60px}h1{font-size:clamp(28px,5vw,40px);margin:0 0 6px}
.top{color:var(--mut);margin:0 0 18px}.sub{color:var(--mut);margin:0 0 14px;font-size:16px}
.tabs{display:flex;gap:8px;margin:0 0 18px;flex-wrap:wrap}
.tab{font:inherit;font-weight:600;padding:9px 16px;border-radius:10px;border:2px solid var(--ink);background:transparent;color:var(--ink);cursor:pointer}
.tab[aria-pressed=true]{background:var(--ink);color:var(--bg)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}
.chip{font:inherit;font-size:14px;padding:5px 12px;border-radius:99px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.chip[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.chip:focus-visible,.tab:focus-visible,a:focus-visible{outline:3px solid var(--acc);outline-offset:2px}
ul{list-style:none;padding:0;margin:0}
li{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--acc);border-radius:12px;padding:14px 16px;margin-bottom:12px}
li a{color:var(--ink);font-weight:600;text-decoration:none}li a:hover{text-decoration:underline}
.meta{font-size:14px;color:var(--mut)}.tags span{display:inline-block;margin:8px 8px 0 0;padding:2px 10px;border-radius:99px;background:var(--acc);color:#0E2740;font-size:14px;font-weight:600}
.tags .k{background:transparent;color:var(--mut);border:1px solid var(--line);font-weight:500}
.tags .best{background:var(--good);color:#fff}
.novo{background:var(--acc);color:#0E2740;border-radius:10px;padding:10px 14px;margin:0 0 16px;font-weight:600}.novo button{font:inherit;margin-left:8px;padding:3px 12px;border-radius:8px;border:2px solid #0E2740;background:#fff;color:#0E2740;cursor:pointer}
footer{color:var(--mut);font-size:14px;margin-top:28px}</style></head><body><main>
<h1>Radar de Milhas</h1><p class="top">Ofertas dos últimos {{DAYS}} dias. Última mudança na lista: {{UPDATED}}. A busca roda a cada 15 minutos.</p>
<div id="novo" class="novo" hidden>Há novidades. <button id="recarregar">Atualizar a página</button></div>
<div class="tabs" role="group" aria-label="Escolher lista">{{TABS}}</div>
{{SECS}}
<footer>Lista montada automaticamente a partir dos títulos de blogs do setor; cada item leva à matéria original. Preços e valores só aparecem quando estão no título. Confira prazo, regras e disponibilidade no site da companhia ou do programa antes de comprar.</footer>
</main>
<script>
function wire(sec){var chips=sec.querySelectorAll('.chip'),items=sec.querySelectorAll('li[data-p]');
chips.forEach(function(c){c.addEventListener('click',function(){
chips.forEach(function(x){x.setAttribute('aria-pressed','false')});c.setAttribute('aria-pressed','true');
items.forEach(function(i){i.hidden=c.dataset.p!=='all'&&i.dataset.p!==c.dataset.p})})})}
var secs=document.querySelectorAll('.sec'),tabs=document.querySelectorAll('.tab');
secs.forEach(wire);
tabs.forEach(function(t){t.addEventListener('click',function(){
tabs.forEach(function(x){x.setAttribute('aria-pressed','false')});t.setAttribute('aria-pressed','true');
secs.forEach(function(s){s.hidden=s.dataset.s!==t.dataset.s})})});
var base=null;
function checar(){fetch(location.href,{cache:'no-store'}).then(function(r){return r.text()}).then(function(t){
if(base===null){base=t}else if(t!==base){document.getElementById('novo').hidden=false}}).catch(function(){})}
document.getElementById('recarregar').addEventListener('click',function(){location.reload()});
checar();setInterval(checar,300000);
</script></body></html>"""

if __name__ == "__main__":
    main()
