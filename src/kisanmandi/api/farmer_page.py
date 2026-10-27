"""Self-contained, mobile-friendly price comparison page.

No third-party scripts, fonts, styles or images. All displayed price data comes
from the user's configured database via the farmer endpoints.
"""

FARMER_PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Compare mandi prices | KisanMandi</title>
<style>
  :root{color-scheme:dark;--bg:#0b1712;--panel:#14261c;--panel2:#1a3023;--border:#2f4939;--text:#eff5eb;--muted:#b2c3b3;--green:#b8ed8b;--orange:#f7ce8d;--ink:#132417}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.5}
  a{color:var(--green)}
  button,input,select{font:inherit}
  :focus-visible{outline:3px solid #e9f7a0;outline-offset:3px}
  .shell{width:min(1120px,calc(100% - 40px));margin:auto}
  .topbar{border-bottom:1px solid var(--border)}
  .nav{min-height:74px;display:flex;align-items:center;justify-content:space-between;gap:18px}
  .brand{display:flex;align-items:center;gap:10px;color:var(--text);font-weight:750;letter-spacing:-.025em;text-decoration:none;font-size:1.13rem}
  .mark{width:34px;height:34px;display:grid;place-items:center;border-radius:11px;background:var(--green);color:#173c24}
  .nav-right{display:flex;align-items:center;gap:18px}
  .nav-tag{color:var(--muted);font-size:.77rem;letter-spacing:.07em;text-transform:uppercase}
  .nav-link{font-size:.88rem;color:var(--text);text-decoration:none;white-space:nowrap}
  .nav-link:hover{text-decoration:underline}
  .hero{display:grid;grid-template-columns:minmax(0,1fr) 275px;gap:46px;align-items:end;padding:62px 0 40px}
  .eyebrow{display:flex;align-items:center;gap:9px;color:var(--green);font-size:.75rem;letter-spacing:.13em;text-transform:uppercase;font-weight:750}
  .dot{width:7px;height:7px;background:var(--green);border-radius:50%}
  h1{max-width:700px;font-size:clamp(2.25rem,5.2vw,4.2rem);line-height:1.04;letter-spacing:-.055em;margin:16px 0 16px;font-weight:750}
  h1 span{color:var(--green)}
  .intro{color:#ceddce;max-width:620px;font-size:1.06rem;line-height:1.7;margin:0}
  .hero-note{border-left:1px solid var(--border);padding:4px 0 4px 20px}
  .hero-note strong{display:block;color:#e8f2e4;font-size:.88rem;margin-bottom:7px}
  .hero-note p{margin:0;color:var(--muted);font-size:.84rem;line-height:1.6}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:18px;padding:26px}
  .panel-head{display:flex;justify-content:space-between;gap:16px;align-items:start;margin-bottom:23px}
  .panel-head h2,.result-head h2{margin:0;font-size:1.18rem;letter-spacing:-.025em}
  .panel-head p,.result-head p{color:var(--muted);font-size:.88rem;margin:5px 0 0}
  .step{border:1px solid #526b50;border-radius:99px;padding:4px 10px;color:var(--green);font-size:.72rem;letter-spacing:.07em;white-space:nowrap;text-transform:uppercase}
  .fields{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:12px;align-items:end}
  label{display:block;color:#e9f2e8;font-size:.8rem;font-weight:650;margin-bottom:7px}
  select,input{width:100%;min-height:47px;border:1px solid #49624d;border-radius:9px;background:#0d1d14;color:var(--text);padding:0 12px}
  select:disabled,input:disabled{opacity:.5;cursor:not-allowed}
  button{border:0;border-radius:9px;min-height:47px;padding:0 21px;background:var(--green);color:var(--ink);font-weight:750;cursor:pointer}
  button:hover:not(:disabled){background:#cdf6a9}
  button:disabled{opacity:.45;cursor:not-allowed}
  .form-status{min-height:22px;margin:13px 0 0;color:var(--muted);font-size:.82rem}
  .form-status.error{color:#ffd7a0}
  .notice{margin-top:20px;background:#202b1f;border:1px solid #536143;border-radius:11px;padding:14px 16px;color:#e6ebd8;font-size:.85rem;line-height:1.6}
  .notice strong{color:#f5daa5}
  .results{padding:43px 0 55px}
  .result-head{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:19px}
  .result-count{color:var(--muted);font-size:.8rem;text-align:right}
  .empty{border:1px dashed #405b46;border-radius:14px;padding:30px;color:var(--muted);font-size:.9rem;text-align:center}
  .cards{display:grid;gap:13px}
  .market-card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:21px;display:grid;grid-template-columns:minmax(0,1fr) 220px 215px;gap:24px;align-items:start}
  .market-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
  .market-head h3{margin:0;font-size:1.03rem;letter-spacing:-.02em;overflow-wrap:anywhere}
  .badge{font-size:.68rem;border-radius:99px;border:1px solid #526b50;color:var(--green);padding:3px 8px;white-space:nowrap}
  .badge.old{color:#f7d39b;border-color:#8b7047}
  .meta{margin:9px 0 0;color:var(--muted);font-size:.82rem;line-height:1.7;overflow-wrap:anywhere}
  .meta strong{color:#d8e7d6;font-weight:600}
  .price-label,.estimate-label{color:var(--muted);font-size:.72rem;letter-spacing:.075em;text-transform:uppercase;font-weight:650}
  .price{font-size:1.72rem;line-height:1.15;font-weight:750;letter-spacing:-.04em;margin:7px 0 3px}
  .per-unit{font-size:.78rem;color:var(--muted)}
  .cost label{margin:0 0 7px}
  .cost input{display:block;min-height:41px;margin-top:7px}
  .estimate{margin:11px 0 0;color:var(--green);font-size:1.07rem;font-weight:700;overflow-wrap:anywhere}
  .estimate small{display:block;color:var(--muted);font-size:.74rem;font-weight:400;margin-top:2px}
  footer{border-top:1px solid var(--border);color:var(--muted);font-size:.78rem}
  .foot{display:flex;justify-content:space-between;gap:20px;padding:22px 0 30px}
  @media(max-width:800px){.hero{grid-template-columns:1fr;gap:25px;padding:45px 0 32px}.hero-note{max-width:560px}.fields{grid-template-columns:1fr 1fr}.fields button{width:100%}.market-card{grid-template-columns:1fr 1fr}.market-details{grid-column:1/-1}.cost{max-width:240px}}
  @media(max-width:500px){.shell{width:min(100% - 28px,1120px)}.nav-tag{display:none}.hero{padding-top:37px}h1{font-size:2.55rem}.panel{padding:19px}.fields{grid-template-columns:1fr}.market-card{grid-template-columns:1fr;gap:17px}.market-details{grid-column:auto}.cost{max-width:none}.foot{display:block}.foot p{margin:6px 0}.panel-head{align-items:start}.result-head{align-items:start}}
</style>
</head>
<body>
<header class="topbar">
  <div class="shell nav">
    <a class="brand" href="/farmers" aria-label="KisanMandi farmer prices">
      <span class="mark" aria-hidden="true"><svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M12 21V8m0 6C7 14 5 11 5 8c4 0 7 2 7 6Zm0-4c0-4 2-6 5-7 1 4-1 7-5 7Zm0 8c4 0 7-2 7-5-4 0-7 1-7 5Z"/></svg></span>
      KisanMandi
    </a>
    <div class="nav-right"><span class="nav-tag">Farmer price guide</span><a class="nav-link" href="/">Project dashboard &rarr;</a></div>
  </div>
</header>
<main class="shell">
  <section class="hero" aria-labelledby="hero-title">
    <div>
      <div class="eyebrow"><span class="dot"></span> Reported mandi prices</div>
      <h1 id="hero-title">A clearer view of <span>mandi prices.</span></h1>
      <p class="intro">Compare the prices stored for your crop and district, then estimate what remains after transport.</p>
    </div>
    <aside class="hero-note"><strong>Before you decide</strong><p>Prices are reported observations, not guaranteed offers. Confirm the price and crop quality with the mandi before travelling.</p></aside>
  </section>
  <section class="panel" aria-labelledby="search-heading">
    <div class="panel-head"><div><h2 id="search-heading">Find a market report</h2><p>Choose from the locations and crops in the stored data.</p></div><span class="step">Start here</span></div>
    <form id="price-form">
      <div class="fields">
        <div><label for="state">State</label><select id="state" required disabled><option value="">Loading states…</option></select></div>
        <div><label for="district">District</label><select id="district" required disabled><option value="">Choose a state first</option></select></div>
        <div><label for="commodity">Crop</label><select id="commodity" required disabled><option value="">Choose a district first</option></select></div>
        <button id="find" type="submit" disabled>Show prices <span aria-hidden="true">&rarr;</span></button>
      </div>
      <p id="form-status" class="form-status" role="status" aria-live="polite">Loading stored locations…</p>
    </form>
    <div class="notice"><strong>Compare like with like.</strong> Check each report’s date, crop variety and grade. Prices can change, and transport or other costs may differ between markets.</div>
  </section>
  <section class="results" aria-labelledby="results-heading">
    <div class="result-head"><div><h2 id="results-heading">Market reports</h2><p>Latest stored observation for each market, variety and grade.</p></div><span id="result-count" class="result-count"></span></div>
    <div id="results" class="cards" aria-live="polite"><div class="empty">Select a state, district and crop to see stored prices.</div></div>
  </section>
</main>
<footer><div class="shell foot"><p>Source: Agmarknet via data.gov.in &middot; ₹/quintal (100 kg)</p><p>Transport entries stay in this browser. Other fees and losses are not included.</p></div></footer>
<noscript><div class="shell notice">JavaScript is needed to choose locations and calculate transport estimates on this page.</div></noscript>
<script>
(() => {
  'use strict';
  const state = document.getElementById('state');
  const district = document.getElementById('district');
  const commodity = document.getElementById('commodity');
  const find = document.getElementById('find');
  const status = document.getElementById('form-status');
  const results = document.getElementById('results');
  const resultCount = document.getElementById('result-count');
  const form = document.getElementById('price-form');
  const money = new Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR', maximumFractionDigits: 2});
  const dates = new Intl.DateTimeFormat('en-IN', {day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC'});
  let sequence = 0;

  function text(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = value;
    return element;
  }
  function message(value, isError = false) {
    status.textContent = value;
    status.classList.toggle('error', isError);
  }
  function options(select, values, prompt) {
    select.replaceChildren();
    const first = document.createElement('option');
    first.value = '';
    first.textContent = prompt;
    select.append(first);
    for (const value of values) {
      const item = document.createElement('option');
      item.value = value;
      item.textContent = value;
      select.append(item);
    }
    select.disabled = values.length === 0;
  }
  function clearResults(value = 'Select a state, district and crop to see stored prices.') {
    results.replaceChildren(text('div', 'empty', value));
    resultCount.textContent = '';
  }
  function updateButton() {
    find.disabled = !(state.value && district.value && commodity.value);
  }
  async function readJson(path) {
    const response = await fetch(path, {headers: {'Accept': 'application/json'}});
    if (!response.ok) throw new Error('The price service could not be reached.');
    return response.json();
  }
  function query(path, params) {
    return path + '?' + new URLSearchParams(params).toString();
  }
  function formattedDate(iso) {
    const date = new Date(iso + 'T00:00:00Z');
    return Number.isNaN(date.getTime()) ? iso : dates.format(date);
  }
  function createCard(row, staleAfter) {
    const card = document.createElement('article');
    card.className = 'market-card';
    const details = document.createElement('div');
    details.className = 'market-details';
    const heading = document.createElement('div');
    heading.className = 'market-head';
    heading.append(text('h3', '', row.market || 'Market not stated'));
    let badge = 'Stored report';
    if (row.is_future) badge = 'Check report date';
    else if (row.is_stale) badge = 'Older than ' + staleAfter + ' days';
    heading.append(text('span', 'badge' + (row.is_stale || row.is_future ? ' old' : ''), badge));
    details.append(heading);
    const meta = document.createElement('p');
    meta.className = 'meta';
    meta.append(text('strong', '', 'Reported: '), document.createTextNode(formattedDate(row.reported_date)));
    meta.append(document.createElement('br'), text('strong', '', 'Variety: '), document.createTextNode(row.variety || 'Not stated'));
    meta.append(document.createElement('br'), text('strong', '', 'Grade: '), document.createTextNode(row.grade || 'Not stated'));
    details.append(meta);
    const priceBox = document.createElement('div');
    priceBox.append(text('div', 'price-label', 'Reported modal price'));
    const price = row.modal_price === null ? null : Number(row.modal_price);
    const priceValid = price !== null && Number.isFinite(price);
    priceBox.append(text('div', 'price', priceValid ? money.format(price) : 'Not reported'));
    priceBox.append(text('div', 'per-unit', 'per quintal · not a confirmed offer'));
    const costBox = document.createElement('div');
    costBox.className = 'cost';
    const label = document.createElement('label');
    label.textContent = 'Transport cost (₹ / quintal)';
    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.max = '1000000';
    input.step = '0.01';
    input.inputMode = 'decimal';
    input.placeholder = 'Enter your cost';
    input.setAttribute('aria-label', 'Transport cost per quintal for ' + (row.market || 'this market'));
    input.disabled = !priceValid;
    label.append(input);
    const estimateLabel = text('div', 'estimate-label', 'After transport');
    const estimate = text('div', 'estimate', priceValid ? 'Enter cost to estimate' : 'Price unavailable');
    function updateEstimate() {
      if (input.value.trim() === '') {
        estimate.textContent = 'Enter cost to estimate';
        return;
      }
      const amount = Number(input.value);
      if (!input.validity.valid || !Number.isFinite(amount) || amount < 0) {
        estimate.textContent = 'Enter a valid non-negative cost';
        return;
      }
      estimate.textContent = money.format(price - amount) + ' / quintal';
      estimate.append(text('small', '', 'Estimate only; other costs excluded'));
    }
    input.addEventListener('input', updateEstimate);
    costBox.append(label, estimateLabel, estimate);
    card.append(details, priceBox, costBox);
    return card;
  }
  state.addEventListener('change', async () => {
    const current = ++sequence;
    options(district, [], 'Choose a state first');
    options(commodity, [], 'Choose a district first');
    clearResults();
    updateButton();
    if (!state.value) { message('Choose a state to continue.'); return; }
    message('Loading districts…');
    try {
      const data = await readJson(query('/v1/farmer/options', {state: state.value}));
      if (current !== sequence) return;
      options(district, data.districts, data.districts.length ? 'Choose district' : 'No districts available');
      message(data.districts.length ? 'Now choose a district.' : 'No districts are stored for this state.');
    } catch (_) { if (current === sequence) message('Could not load districts. Refresh the page and try again.', true); }
  });
  district.addEventListener('change', async () => {
    const current = ++sequence;
    options(commodity, [], 'Choose a district first');
    clearResults();
    updateButton();
    if (!district.value) { message('Choose a district to continue.'); return; }
    message('Loading crops…');
    try {
      const data = await readJson(query('/v1/farmer/options', {state: state.value, district: district.value}));
      if (current !== sequence) return;
      options(commodity, data.commodities, data.commodities.length ? 'Choose crop' : 'No crops available');
      message(data.commodities.length ? 'Now choose a crop.' : 'No crops are stored for this district.');
    } catch (_) { if (current === sequence) message('Could not load crops. Refresh the page and try again.', true); }
  });
  commodity.addEventListener('change', () => {
    ++sequence;
    clearResults();
    updateButton();
    message(commodity.value ? 'Ready to show stored reports.' : 'Choose a crop to continue.');
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!state.value || !district.value || !commodity.value) return;
    const current = ++sequence;
    find.disabled = true;
    message('Loading market reports…');
    try {
      const data = await readJson(query('/v1/farmer/prices', {state: state.value, district: district.value, commodity: commodity.value}));
      if (current !== sequence) return;
      if (!data.records.length) {
        clearResults('No stored observations match this selection.');
        message('No matching prices are stored yet.');
        return;
      }
      results.replaceChildren(...data.records.map(row => createCard(row, data.stale_after_days)));
      resultCount.textContent = data.records.length + (data.records.length === 1 ? ' report' : ' reports') + (data.truncated ? ' · showing the first 100' : '');
      const hasOld = data.records.some(row => row.is_stale || row.is_future);
      message(hasOld ? 'Some reports are old or have an unusual date. Check the dates before using them.' : 'These are stored reports, not guaranteed current offers.');
    } catch (_) { if (current === sequence) { clearResults('Could not load reports.'); message('Could not load prices. Please try again.', true); } }
    finally { if (current === sequence) updateButton(); }
  });
  (async () => {
    try {
      const data = await readJson('/v1/farmer/options');
      options(state, data.states, data.states.length ? 'Choose state' : 'No states available');
      message(data.states.length ? 'Choose a state to begin.' : 'No prices are stored yet. Run an ingest first.');
      if (!data.states.length) clearResults('No stored prices are available yet.');
    } catch (_) { options(state, [], 'Could not load states'); message('Could not load stored locations. Refresh the page and try again.', true); }
  })();
})();
</script>
</body>
</html>"""
