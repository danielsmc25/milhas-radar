#!/usr/bin/env python3
"""Radar de Milhas: coleta ofertas de compra de milhas/pontos em feeds RSS e gera docs/index.html.
Sem dependências externas. Cada oferta aponta para a matéria original (não copiamos o texto)."""
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

DAYS = 3  # ofertas de milhas duram pouco; aumente se quiser ver mais histórico

# Só entram ofertas de compra de milhas/pontos, milheiro, transferência bonificada e clubes com bônus.
BUY = re.compile("|".join([
    r"compr(a|ar|e|ando)\s+(de\s+)?(até\s+)?[\d\.]*\s*(mil\s+)?(milhas|pontos)",
    r"milheiro",
    r"transfer[êe]ncias?\s+bonificadas?",
    r"b[ôo]nus.{0,40}transfer[êe]ncia",
    r"\d+%\s+de\s+desconto.{0,30}(compra|milhas|pontos)",
    r"clube.{0,40}b[ôo]nus",
]), re.I)
# Fora: passagens, emissões, produtos, cupons e seguros.
NOT_BUY = re.compile(r"(passagens?|voos?|emiss(ão|ões|ao)|iphone|celular|smartphone|notebook|geladeira|cupom|seguro|aluguel de carro)", re.I)

# Nome exibido -> variações que aparecem nos títulos
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
    "Hilton Honors": ["hilton"],
    "Connectmiles": ["connectmiles"],
}
UA = {"User-Agent": "milhas-radar/2.0 (+leitor de RSS pessoal)"}

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

def find_program(title):
    """Acha o programa mais citado. Em 'X para Y' vale o destino (Y), que recebe o bônus."""
    low = title.lower()
    parts = re.split(r"\spara\s", low, maxsplit=1)
    for text in ([parts[1], low] if len(parts) == 2 else [low]):
        best = None
        for name, aliases in PROGRAMS.items():
            for a in aliases:
                m = re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text)
                if m and (best is None or m.start() < best[0]):
                    best = (m.start(), name)
        if best:
            return best[1]
    return "Outros"

def find_cpm(title):
    m = re.search(r"milheiro.{0,40}?R\$\s?(\d{1,3}(?:,\d{1,2})?)", title, re.I) \
        or re.search(r"R\$\s?(\d{1,3}(?:,\d{1,2})?)[^.]{0,25}(o\s+)?milheiro", title, re.I)
    return float(m.group(1).replace(",", ".")) if m else None

def kind(title):
    if re.search(r"transfer", title, re.I):
        return "Transferência bonificada"
    if re.search(r"compr|milheiro", title, re.I):
        return "Compra"
    if re.search(r"clube", title, re.I):
        return "Clube"
    return "Oferta"

def enrich(o):
    t = o["title"]
    o["program"] = find_program(t)
    o["kind"] = kind(t)
    o["cpm"] = find_cpm(t)
    pct = re.search(r"(\d{2,3})\s?%", t)
    o["percent"] = pct.group(1) + "%" if pct else ""
    return o

def brl(v):
    return "R$ " + f"{v:.2f}".replace(".", ",")

def render(offers, now):
    progs = {}
    for o in offers:
        progs[o["program"]] = progs.get(o["program"], 0) + 1
    chips = '<button class="chip" data-p="all" aria-pressed="true">Todos (%d)</button>' % len(offers) + "".join(
        f'<button class="chip" data-p="{html.escape(p)}" aria-pressed="false">{html.escape(p)} ({n})</button>'
        for p, n in sorted(progs.items(), key=lambda x: (x[0] == "Outros", x[0])))
    first_cpm = next((i for i, o in enumerate(offers) if o["cpm"] is not None), None)
    items = []
    for i, o in enumerate(offers):
        tags = []
        if i == first_cpm:
            tags.append('<span class="best">Menor milheiro</span>')
        if o["cpm"] is not None:
            tags.append(f'<span>milheiro {brl(o["cpm"])}</span>')
        if o["percent"]:
            tags.append(f'<span>{o["percent"]}</span>')
        tags.append(f'<span class="k">{html.escape(o["kind"])}</span>')
        items.append(
            f'<li data-p="{html.escape(o["program"])}"><div class="meta"><b>{html.escape(o["program"])}</b>'
            f' · {o["date"].astimezone(now.tzinfo):%d/%m %H:%M} · {html.escape(o["source"])}</div>'
            f'<a href="{html.escape(o["link"])}" rel="noopener">{html.escape(o["title"])}</a>'
            f'<div class="tags">{"".join(tags)}</div></li>')
    rows = "".join(items) or "<li>Nenhuma oferta de compra encontrada nos últimos dias.</li>"
    return (TEMPLATE.replace("{{CHIPS}}", chips).replace("{{ROWS}}", rows)
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
            if BUY.search(o["title"]) and not NOT_BUY.search(o["title"]):
                seen.add(o["link"])
                offers.append(enrich(o))
    # Menor milheiro primeiro; ofertas sem valor no título vêm depois, das mais novas às mais antigas.
    offers.sort(key=lambda o: (o["cpm"] is None, o["cpm"] or 0, -o["date"].timestamp()))
    now = datetime.now(timezone(timedelta(hours=-3)))
    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump([{**o, "date": o["date"].isoformat()} for o in offers], f, ensure_ascii=False, indent=1)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(render(offers, now))
    print(f"{len(offers)} ofertas gravadas.")

TEMPLATE = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Radar de Milhas — ofertas de compra</title>
<style>:root{--bg:#F6F9FC;--ink:#0E2740;--mut:#4D6178;--card:#fff;--line:#D3DEE9;--acc:#FFB81C;--good:#0B7A4B}
@media(prefers-color-scheme:dark){:root{--bg:#0A1827;--ink:#EAF2FA;--mut:#9DB2C7;--card:#112338;--line:#25405C;--good:#4FD39A}}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 system-ui,sans-serif}
main{max-width:780px;margin:0 auto;padding:28px 20px 60px}h1{font-size:clamp(28px,5vw,40px);margin:0 0 6px}
.sub{color:var(--mut);margin:0 0 18px}.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}
.chip{font:inherit;font-size:14px;padding:5px 12px;border-radius:99px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.chip[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.chip:focus-visible,a:focus-visible{outline:3px solid var(--acc);outline-offset:2px}
ul{list-style:none;padding:0;margin:0}
li{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--acc);border-radius:12px;padding:14px 16px;margin-bottom:12px}
li a{color:var(--ink);font-weight:600;text-decoration:none}li a:hover{text-decoration:underline}
.meta{font-size:14px;color:var(--mut)}.tags span{display:inline-block;margin:8px 8px 0 0;padding:2px 10px;border-radius:99px;background:var(--acc);color:#0E2740;font-size:14px;font-weight:600}
.tags .k{background:transparent;color:var(--mut);border:1px solid var(--line);font-weight:500}
.tags .best{background:var(--good);color:#fff}
footer{color:var(--mut);font-size:14px;margin-top:28px}</style></head><body><main>
<h1>Radar de Milhas</h1><p class="sub">Ofertas de compra de milhas e pontos dos últimos {{DAYS}} dias, do menor para o maior valor do milheiro. Atualizado em {{UPDATED}}.</p>
<div class="chips" role="group" aria-label="Filtrar por programa">{{CHIPS}}</div>
<ul>{{ROWS}}</ul>
<footer>Lista montada automaticamente a partir dos títulos de blogs do setor; cada item leva à matéria original. O valor do milheiro só aparece quando está no título, então ofertas sem valor ficam no fim da lista. Confira prazo, plano e regras no site do programa antes de comprar.</footer>
</main>
<script>
var chips=document.querySelectorAll('.chip'),items=document.querySelectorAll('li[data-p]');
chips.forEach(function(c){c.addEventListener('click',function(){
chips.forEach(function(x){x.setAttribute('aria-pressed','false')});c.setAttribute('aria-pressed','true');
items.forEach(function(i){i.hidden=c.dataset.p!=='all'&&i.dataset.p!==c.dataset.p})})});
</script></body></html>"""

if __name__ == "__main__":
    main()
