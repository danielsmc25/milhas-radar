
#!/usr/bin/env python3
"""Radar de Milhas: RSS, site estático e alertas Telegram (biblioteca padrão)."""
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FEEDS = {
    "Passageiro de Primeira": "https://passageirodeprimeira.com/feed/",
    "Melhores Cartões": "https://www.melhorescartoes.com.br/feed",
    "Melhores Destinos": "https://www.melhoresdestinos.com.br/feed",
    "Pontos pra Voar": "https://pontospravoar.com/feed/",
}
if os.environ.get("FEEDS"):
    FEEDS = dict(item.split("=", 1) for item in os.environ["FEEDS"].split(";") if "=" in item)

DAYS = 3
STATE = Path("alertas_enviados.json")
DOCS = Path("docs")
UA = {"User-Agent": "milhas-radar/5.0 (RSS reader)"}
PROGRAMS = {
    "Smiles": ["smiles"],
    "LATAM Pass": ["latam pass", "latampass"],
    "Azul Fidelidade": ["azul fidelidade", "tudoazul", "pontos azul"],
    "Livelo": ["livelo"],
    "Esfera": ["esfera"],
    "Avios": ["avios"],
    "Flying Blue": ["flying blue"],
    "TAP Miles&Go": ["miles&go", "tap miles"],
}
AIRLINES = {
    "LATAM": ["latam"], "Azul": ["azul"], "GOL": ["gol"],
    "TAP": ["tap"], "Lufthansa": ["lufthansa"],
    "Air France": ["air france"], "KLM": ["klm"],
    "Copa": ["copa airlines"], "Avianca": ["avianca"],
    "Iberia": ["iberia"], "American Airlines": ["american airlines"],
    "United": ["united airlines"], "Delta": ["delta"],
    "Emirates": ["emirates"], "Qatar": ["qatar"],
    "British Airways": ["british airways"],
}


def fetch(url):
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def parse(source, content):
    root = ET.fromstring(content)
    for item in root.iter():
        if item.tag.split("}")[-1] != "item":
            continue
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        try:
            date = parsedate_to_datetime(item.findtext("pubDate"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, IndexError):
            continue
        if title and link:
            yield {"title": title, "link": link, "date": date, "source": source}


def entity(title, names, default):
    for name, aliases in names.items():
        if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", title, re.I) for alias in aliases):
            return name
    return default


def price_value(value):
    return float(value.replace(".", "").replace(",", "."))


def find_cpm(title):
    match = (re.search(r"milheiro.{0,40}?R\$\s*([\d.,]+)", title, re.I)
             or re.search(r"R\$\s*([\d.,]+).{0,30}milheiro", title, re.I))
    return price_value(match.group(1).rstrip(".,")) if match else None


def find_fare(title):
    match = re.search(r"(?:a partir de|por apenas|por|apenas|só|a)\s+R\$\s*([\d.,]+)", title, re.I)
    return price_value(match.group(1).rstrip(".,")) if match else None


def find_discount(title):
    match = (re.search(r"R\$\s*([\d.,]+)\s*(?:de\s+)?(?:off|desconto)", title, re.I)
             or re.search(r"(?:cupom|desconto)\s+de\s+(?:até\s+)?R\$\s*([\d.,]+)", title, re.I))
    return price_value(match.group(1).rstrip(".,")) if match else None


def classify(offer):
    title = offer["title"]
    if re.search(r"iphone|celular|smartphone|notebook|geladeira", title, re.I):
        return None
    percentage = re.search(r"(\d{1,3})\s*%", title)
    offer["percent"] = percentage.group(1) + "%" if percentage else ""
    transfer = bool(re.search(r"transfer[eê]ncia|transferir|transfira|bonificad|b[oô]nus.{0,40}(?:pontos|milhas|transfer)", title, re.I))
    points = bool(re.search(r"milhas?|pontos?|milheiro|smiles|livelo|esfera|latam pass|azul fidelidade|tudoazul", title, re.I))
    purchase = bool(re.search(r"compr[ae]|comprar|adquirir|milheiro|clube.{0,40}b[oô]nus", title, re.I))
    if transfer and points:
        offer.update(cat="milhas", entity=entity(title, PROGRAMS, "Outros programas"),
                     kind="Transferência bonificada", cpm=None, fare=None,
                     discount=find_discount(title))
        return offer
    if purchase and points:
        offer.update(cat="milhas", entity=entity(title, PROGRAMS, "Outros programas"),
                     kind="Compra de milhas ou pontos", cpm=find_cpm(title), fare=None,
                     discount=find_discount(title))
        return offer
    fare = re.search(r"passagens?|voos?|trechos?|ida e volta|ida\+volta|emiss(?:ão|ões|ao)|resgate", title, re.I)
    deal = re.search(r"R\$\s*\d|desconto|promo|\boff\b|barat|cupom|imperd|rel[aâ]mpago|liquida|black", title, re.I)
    if fare and deal:
        with_points = bool(re.search(r"milhas|pontos|emiss|resgate", title, re.I))
        offer.update(cat="passagem", entity=entity(title, AIRLINES, "Outras companhias"),
                     kind="Com milhas ou pontos" if with_points else "Em dinheiro",
                     cpm=None, fare=find_fare(title), discount=find_discount(title))
        return offer
    return None


def money(value):
    if value is None:
        return ""
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def telegram(token, chat, message):
    base = os.environ.get("TELEGRAM_API", "https://api.telegram.org").rstrip("/")
    data = urllib.parse.urlencode({"chat_id": chat, "text": message}).encode()
    try:
        request = urllib.request.Request(f"{base}/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise RuntimeError(f"Resposta Telegram: {result}")
        return True
    except Exception as exc:
        print(f"Aviso: falha ao enviar alerta: {exc}")
        return False


def alert_label(offer):
    title = offer["title"]
    if re.search(r"rel[aâ]mpago|[úu]ltimas horas|tempo limitado|somente hoje|flash sale", title, re.I):
        return "🔥 PROMOÇÃO-RELÂMPAGO"
    if offer["kind"] == "Transferência bonificada":
        return "🎁 TRANSFERÊNCIA BONIFICADA"
    if offer["cat"] == "milhas":
        return "💰 MILHAS E PONTOS"
    if re.search(r"internacional|exterior|europa|estados unidos|argentina|chile|portugal|paris|miami|orlando", title, re.I):
        return "🌎 OFERTA INTERNACIONAL"
    return "✈️ PASSAGENS EM PROMOÇÃO"


def alerts(offers):
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        print("Aviso: TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configurado.")
        return

    if os.environ.get("TESTE_TELEGRAM") == "1":
        if not telegram(token, chat, "✈️ Radar de Milhas — TESTE\n✅ Telegram funcionando!"):
            raise RuntimeError("Falha no teste do Telegram")
        print("Teste do Telegram enviado.")
        return

    try:
        with STATE.open(encoding="utf-8") as file:
            sent = json.load(file)
        if not isinstance(sent, list):
            sent = []
    except FileNotFoundError:
        sent = []

    sent_set = set(sent)
    new = [offer for offer in offers if offer["link"] not in sent_set]
    print(f"Ofertas novas para alertar: {len(new)}")
    for offer in new:
        message = (f"{alert_label(offer)}\n"
                   f"📢 {offer['entity']}\n\n"
                   f"{offer['title']}\n\n"
                   f"🔗 {offer['link']}")
        if telegram(token, chat, message):
            sent.append(offer["link"])
            sent_set.add(offer["link"])
            # Grava após cada sucesso para evitar reenvio se a execução for interrompida.
            with STATE.open("w", encoding="utf-8") as file:
                json.dump(sent[-5000:], file, ensure_ascii=False)
        else:
            print(f"Falha ao enviar: {offer['link']}")


def render(offers, now):
    sections = []
    for category, heading in (("milhas", "💰 Milhas e pontos"), ("passagem", "✈️ Passagens em promoção")):
        rows = []
        for offer in offers:
            if offer["cat"] != category:
                continue
            title = html.escape(offer["title"])
            url = html.escape(offer["link"], quote=True)
            source = html.escape(offer["source"])
            airline = html.escape(offer["entity"])
            kind = html.escape(offer["kind"])
            price = offer["cpm"] if category == "milhas" else offer["fare"]
            label = ("Milheiro " if category == "milhas" else "A partir de ") + money(price) if price is not None else "Preço não informado"
            date = offer["date"].astimezone(now.tzinfo).strftime("%d/%m %H:%M")
            rows.append(f'<article class="offer"><div class="meta">{airline} · {source} · {date}</div>'
                        f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
                        f'<div class="tags"><span>{kind}</span><span>{html.escape(label)}</span></div></article>')
        sections.append(f'<section><h2>{heading} <small>({len(rows)})</small></h2>'
                        + ("".join(rows) or '<p>Nenhuma oferta recente encontrada.</p>') + '</section>')
    return """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Promoções de passagens, milhas e pontos em todo o Brasil.">
<title>Radar de Milhas | Alertas de promoções</title>
<style>
:root{color-scheme:light dark;font-family:system-ui,Arial,sans-serif}
*{box-sizing:border-box}body{margin:0;background:#f1f5f9;color:#14263c}
header{background:linear-gradient(125deg,#0b2a4a,#12679a);color:white;padding:40px 20px}
header>div,main,footer{max-width:1000px;margin:auto}h1{font-size:clamp(30px,5vw,48px);margin:0}
header p{font-size:18px;color:#d9ebfa}main{padding:28px 18px}
h2{margin:32px 0 16px}small{font-weight:400;color:#62758a}
.offer{background:white;border:1px solid #dce6ef;border-radius:14px;padding:19px;margin:12px 0;box-shadow:0 2px 10px #092b4910}
.meta{color:#5a7189;font-size:13px;margin-bottom:9px}.offer a{color:#124d80;font-weight:700;text-decoration:none;font-size:18px}
.offer a:hover{text-decoration:underline}.tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.tags span{background:#e9f3fc;border-radius:20px;padding:5px 10px;font-size:13px}
footer{padding:20px;color:#60738a;font-size:13px}
@media(prefers-color-scheme:dark){body{background:#081625;color:#e8f2ff}.offer{background:#10263b;border-color:#26415b}.offer a{color:#8ccaff}.tags span{background:#1c3c56}.meta,small,footer{color:#a5bdd2}}
</style></head><body><header><div><h1>✈️ Radar de Milhas</h1>
<p>Passagens aéreas, milhas, pontos e transferências bonificadas.</p>
<p>Atualizado em """ + now.strftime("%d/%m/%Y às %H:%M") + """ (Brasília)</p></div></header>
<main>""" + "".join(sections) + """</main><footer>Ofertas de fontes públicas. Preços e disponibilidade podem mudar.</footer></body></html>"""


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    offers = []
    seen = set()
    for source, url in FEEDS.items():
        try:
            items = list(parse(source, fetch(url)))
            print(f"Fonte {source}: {len(items)} publicações no feed")
        except Exception as exc:
            print(f"Aviso: falha em {source}: {exc}")
            continue
        for item in items:
            if item["date"] < cutoff or item["link"] in seen:
                continue
            classified = classify(item)
            if classified:
                seen.add(item["link"])
                offers.append(classified)

    milhas = sorted((o for o in offers if o["cat"] == "milhas"),
                    key=lambda o: (o["cpm"] is None, o["cpm"] or 0, -o["date"].timestamp()))
    passagens = sorted((o for o in offers if o["cat"] == "passagem"),
                       key=lambda o: (o["fare"] is None, o["fare"] or 0, -o["date"].timestamp()))
    all_offers = milhas + passagens
    now = datetime.now(timezone(timedelta(hours=-3)))
    DOCS.mkdir(parents=True, exist_ok=True)
    with (DOCS / "data.json").open("w", encoding="utf-8") as file:
        json.dump([{**o, "date": o["date"].isoformat()} for o in all_offers],
                  file, ensure_ascii=False, indent=2)
    (DOCS / "index.html").write_text(render(all_offers, now), encoding="utf-8")
    alerts(all_offers)
    print(f"{len(milhas)} ofertas de milhas e {len(passagens)} de passagens gravadas.")


if __name__ == "__main__":
    main()
