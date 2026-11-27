#!/usr/bin/env python3
"""Export quality-approved stored prices as a small, read-only Pages site.

Only price observations are exported. Database diagnostics, host details,
metrics, quarantined rows, and all credentials remain private to the runner.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from kisanmandi.config import Settings
from kisanmandi.storage.db import (
    MandiPrice,
    get_engine,
    init_db,
    make_session_factory,
    session_scope,
)

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="description" content="Reported Karnataka mandi prices from Agmarknet, with clear reporting dates and freshness warnings.">
<title>KisanMandi | Karnataka market prices</title>
<style>
:root{color-scheme:dark;--bg:#0b1712;--panel:#14261c;--line:#2f4939;--text:#eff5eb;--muted:#b2c3b3;--green:#b8ed8b;--amber:#f7ce8d;--red:#ffb4a9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:auto;padding:24px 18px 56px}.brand{color:var(--green);font-weight:800;letter-spacing:.04em;text-transform:uppercase;font-size:.78rem}
h1{font-size:clamp(2rem,6vw,3.35rem);line-height:1.08;letter-spacing:-.04em;margin:.55rem 0}.intro{max-width:700px;color:#d2dfd1}
.notice{border:1px solid #735d31;background:#282414;padding:14px 16px;border-radius:12px;margin:22px 0;color:#f7e4b8}.notice strong{color:var(--amber)}
.filters,.results{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin:16px 0}.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
label{display:grid;gap:6px;font-weight:650;font-size:.9rem}select{width:100%;padding:11px;border:1px solid #55705c;border-radius:9px;background:#0d1d14;color:var(--text);font:inherit}
.status{color:var(--muted);min-height:1.5em}.cards{display:grid;gap:12px;margin-top:14px}.card{border:1px solid var(--line);background:#102018;border-radius:12px;padding:16px;display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center}
.market{font-weight:750;font-size:1.1rem}.meta{color:var(--muted);font-size:.9rem}.price{text-align:right;font-weight:800;color:var(--green);font-size:1.25rem;white-space:nowrap}.price small{display:block;color:var(--muted);font-size:.72rem;font-weight:500}.stale{color:var(--amber);font-size:.84rem;margin-top:5px}.empty{color:var(--muted);padding:10px 0}
footer{border-top:1px solid var(--line);margin-top:28px;padding-top:18px;color:var(--muted);font-size:.88rem}a{color:var(--green)}:focus-visible{outline:3px solid var(--amber);outline-offset:2px}
@media(max-width:560px){.card{grid-template-columns:1fr}.price{text-align:left}.filters{grid-template-columns:1fr}}
</style>
</head>
<body><main>
<div class="brand">KisanMandi · Farmer price guide</div>
<h1>Karnataka mandi prices</h1>
<p class="intro">Compare the latest stored market observations by district and crop. Each result keeps its reported date visible so you can judge how current it is.</p>
<div class="notice"><strong>Important:</strong> These are reported market observations, not guaranteed offers. Prices can change by market, variety, grade, and date. Confirm with the mandi before making a decision. Advice is informational only.</div>
<section class="filters" aria-label="Price filters">
<label for="district">District<select id="district" disabled><option value="">Loading…</option></select></label>
<label for="commodity">Crop<select id="commodity" disabled><option value="">Choose a district first</option></select></label>
</section>
<section class="results" aria-live="polite"><div id="status" class="status">Loading the latest published snapshot…</div><div id="cards" class="cards"></div></section>
<footer><div id="updated">Snapshot time: unavailable</div><div>Source: Agmarknet via data.gov.in. This site is a static, read-only snapshot; automated refreshes may be delayed or fail. No personal data is collected.</div><div><a href="https://github.com/Amar1M/kisanmandi">Project source on GitHub</a></div></footer>
</main>
<script>
'use strict';
const district=document.querySelector('#district'), crop=document.querySelector('#commodity');
const statusEl=document.querySelector('#status'), cards=document.querySelector('#cards'), updated=document.querySelector('#updated');
let records=[]; const DAY_MS=86400000;
function option(select,value,label){const node=document.createElement('option');node.value=value;node.textContent=label;select.append(node)}
function setOptions(select,values,placeholder){select.replaceChildren();option(select,'',placeholder);for(const value of values)option(select,value,value);}
function ageText(dateString){const day=new Date(dateString+'T00:00:00Z');if(Number.isNaN(day.valueOf()))return 'Reporting date unavailable';const age=Math.floor((Date.now()-day.getTime())/DAY_MS);if(age<0)return 'Reported date is in the future; please verify';if(age>7)return `Older observation: reported ${age} days ago`;return `Reported ${age} day${age===1?'':'s'} ago`;}
function render(){cards.replaceChildren();if(!district.value||!crop.value){statusEl.textContent='Choose a district and crop to see observations.';return;}
const rows=records.filter(r=>r.district===district.value&&r.commodity===crop.value).sort((a,b)=>b.arrival_date.localeCompare(a.arrival_date)||a.market.localeCompare(b.market));
statusEl.textContent=rows.length?`${rows.length} latest market observation${rows.length===1?'':'s'} for ${crop.value} in ${district.value}.`:'No observations match those filters in this snapshot.';
for(const row of rows){const card=document.createElement('article');card.className='card';const detail=document.createElement('div');const market=document.createElement('div');market.className='market';market.textContent=row.market||'Market not named';const meta=document.createElement('div');meta.className='meta';meta.textContent=[row.variety,row.grade].filter(Boolean).join(' · ')||'Variety/grade not reported';const stale=document.createElement('div');stale.className='stale';stale.textContent=ageText(row.arrival_date);detail.append(market,meta,stale);const price=document.createElement('div');price.className='price';price.textContent=row.modal_price===null?'Price unavailable':`₹${Number(row.modal_price).toLocaleString('en-IN')}`;const unit=document.createElement('small');unit.textContent='modal price / quintal';price.append(unit);card.append(detail,price);cards.append(card);}}
district.addEventListener('change',()=>{const crops=[...new Set(records.filter(r=>r.district===district.value).map(r=>r.commodity))].sort((a,b)=>a.localeCompare(b));setOptions(crop,crops,'Choose a crop');crop.disabled=!crops.length;render();});crop.addEventListener('change',render);
fetch('./prices.json',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error('Snapshot unavailable');return response.json();}).then(data=>{records=Array.isArray(data.records)?data.records:[];updated.textContent=`Snapshot generated: ${new Date(data.generated_at).toLocaleString()} · ${records.length} observations in this export`;
const districts=[...new Set(records.map(r=>r.district).filter(Boolean))].sort((a,b)=>a.localeCompare(b));setOptions(district,districts,districts.length?'Choose a district':'No districts available');district.disabled=!districts.length;statusEl.textContent=districts.length?'Choose a district and crop to begin.':'No price observations are available in this snapshot.';}).catch(()=>{statusEl.textContent='Could not load the published price snapshot. Please try again later.';setOptions(district,[],'Snapshot unavailable');district.disabled=true;});
</script>
</body></html>
"""


def export_site(
    database_url: str, output_dir: Path, *, generated_at: datetime | None = None
) -> dict:
    engine = get_engine(database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        rows = list(
            session.scalars(
                select(MandiPrice)
                .where(MandiPrice.state == "Karnataka")
                .order_by(MandiPrice.arrival_date.desc(), MandiPrice.id.desc())
            )
        )

    # These public records contain only reported market-price fields. No IDs,
    # ingest logs, quarantined details, environment values, or host metadata.
    records = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        identity = (
            row.state,
            row.district,
            row.market,
            row.commodity,
            row.variety,
            row.grade,
            row.arrival_date.isoformat(),
        )
        if identity in seen:
            continue
        seen.add(identity)
        records.append(
            {
                "state": row.state,
                "district": row.district,
                "market": row.market,
                "commodity": row.commodity,
                "variety": row.variety,
                "grade": row.grade,
                "arrival_date": row.arrival_date.isoformat(),
                "min_price": str(row.min_price) if row.min_price is not None else None,
                "max_price": str(row.max_price) if row.max_price is not None else None,
                "modal_price": str(row.modal_price) if row.modal_price is not None else None,
            }
        )

    if not records:
        raise RuntimeError("Refusing to publish an empty price snapshot.")

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or datetime.now(timezone.utc)
    payload = {
        "source": "Agmarknet via data.gov.in",
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "state_scope": "Karnataka",
        "records": records,
    }
    (output_dir / "prices.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (output_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    return {"records": len(records), "generated_at": payload["generated_at"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("public"))
    parser.add_argument("--database-url", default=Settings().database_url)
    args = parser.parse_args()
    result = export_site(args.database_url, args.output_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
