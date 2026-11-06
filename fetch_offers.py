#!/usr/bin/env python3
"""Coleta ofertas de compra de milhas em feeds RSS de blogs do setor e gera docs/index.html.
Sem dependências externas. Cada oferta aponta para a matéria original (não copiamos o texto)."""
import html, json, os, re, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# Confira se cada endereço de feed responde antes de ligar a rotina (veja o README).
FEEDS = {
    "Passageiro de Primeira": "https://passageirodeprimeira.com/feed/",
    "Melhores Cartões": "https://www.melhorescartoes.com.br/feed",
    "Melhores Destinos": "https://www.melhoresdestinos.com.br/feed",
}
if os.environ.get("FEEDS"):  # para testes: "Nome=url,Nome2=url2"
    FEEDS = dict(p.split("=", 1) for p in os.environ["FEEDS"].split(","))

DAYS = 7
OFFER = re.compile(r"(compra|comprar|compre|bônus|bonus|desconto|milheiro|off)", re.I)
TOPIC = re.compile(r"(milhas|pontos|smiles|latam pass|livelo|azul|esfera|iupp)", re.I)
PROGRAMS = ["Smiles", "LATAM Pass", "Azul Fidelidade", "Livelo", "Esfera", "Iupp",
            "Flying Blue", "MileagePlus", "Hilton Honors", "Connectmiles"]
UA = {"User-Agent": "milhas-radar/1.0 (+leitor de RSS pessoal)"}

def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

def parse(source, xml_bytes):
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
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

def enrich(o):
    t = o["title"]
    o["program"] = next((p for p in PROGRAMS if p.lower() in t.lower()), "Outros")
    pct = re.search(r"(\d{2,3})\s?%", t)
    cpm = re.search(r"R\$\s?(\d{1,3},\d{2})", t)
    o["percent"] = pct.group(1) + "%" if pct else ""
    o["cpm"] = "R$ " + cpm.group(1) if cpm else ""
    return o

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
            if OFFER.search(o["title"]) and TOPIC.search(o["title"]):
                seen.add(o["link"])
                offers.append(enrich(o))
    offers.sort(key=lambda o: o["date"], reverse=True)
    now = datetime.now(timezone(timedelta(hours=-3)))
    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump([{**o, "date": o["date"].isoformat()} for o in offers], f, ensure_ascii=False, indent=1)
    rows = "".join(
        f'<li><div class="meta"><b>{html.escape(o["program"])}</b> · {o["date"].astimezone(now.tzinfo):%d/%m %H:%M}'
        f' · {html.escape(o["source"])}</div>'
        f'<a href="{html.escape(o["link"])}" rel="noopener">{html.escape(o["title"])}</a>'
        + (f'<div class="tags">{"<span>bônus/desc. " + o["percent"] + "</span>" if o["percent"] else ""}'
           f'{"<span>milheiro " + o["cpm"] + "</span>" if o["cpm"] else ""}</div>' if o["percent"] or o["cpm"] else "")
        + "</li>" for o in offers) or "<li>Nenhuma oferta encontrada nos últimos dias.</li>"
    page = TEMPLATE.replace("{{ROWS}}", rows).replace("{{UPDATED}}", f"{now:%d/%m/%Y às %H:%M}").replace("{{DAYS}}", str(DAYS))
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"{len(offers)} ofertas gravadas.")

TEMPLATE = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Radar de Milhas — ofertas de compra</title>
<style>:root{--bg:#F6F9FC;--ink:#0E2740;--mut:#4D6178;--card:#fff;--line:#D3DEE9;--acc:#FFB81C}
@media(prefers-color-scheme:dark){:root{--bg:#0A1827;--ink:#EAF2FA;--mut:#9DB2C7;--card:#112338;--line:#25405C}}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 20px 60px}h1{font-size:clamp(28px,5vw,40px);margin:0 0 6px}
.sub{color:var(--mut);margin:0 0 24px}ul{list-style:none;padding:0;margin:0}
li{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--acc);border-radius:12px;padding:14px 16px;margin-bottom:12px}
li a{color:var(--ink);font-weight:600;text-decoration:none}li a:hover{text-decoration:underline}
.meta{font-size:14px;color:var(--mut)}.tags span{display:inline-block;margin:8px 8px 0 0;padding:2px 10px;border-radius:99px;background:var(--acc);color:#0E2740;font-size:14px;font-weight:600}
footer{color:var(--mut);font-size:14px;margin-top:28px}</style></head><body><main>
<h1>Radar de Milhas</h1><p class="sub">Ofertas de compra de milhas e pontos dos últimos {{DAYS}} dias. Atualizado em {{UPDATED}}.</p>
<ul>{{ROWS}}</ul>
<footer>Lista montada automaticamente a partir dos títulos de blogs do setor; cada item leva à matéria original. Confira prazo, plano e regras no site do programa antes de comprar. Compare sempre com o valor do milheiro que você pagaria.</footer>
</main></body></html>"""

if __name__ == "__main__":
    main()
