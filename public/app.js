/* 군위군 시설관리 우선지역 분석 — 화면 로직
 *
 * 데이터는 빌드 때 HTML에 박아넣지 않고 런타임에 fetch한다.
 * public/data/* 는 tools/build.py 가 생성한다 — 직접 고치지 말 것.
 *
 * 조인은 region_code 하나로만 한다. 지역명 매칭은 tools/prepare.py 가
 * 빌드 시점에 이미 끝내놨다.
 */
'use strict';

const RAMP = ['#eaf1f8', '#c3d9ec', '#8fb9dc', '#5b95c6', '#2f6fb0'];
const state = { period: null, indicator: null, selected: null, sourceFilter: 'all' };
const store = {};
let map, layer, labels;

const $ = (id) => document.getElementById(id);

async function getJSON(path) {
  const res = await fetch(path, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

/* ------------------------------------------------------------------ 조회 */

const rows = () => store.regions.regions[state.period] || [];
const indicatorById = (id) => store.regions.indicators.find((i) => i.id === id);
const rowByCode = (code) => rows().find((r) => r.region_code === code);

function valueOf(row) {
  const v = row[state.indicator];
  return typeof v === 'number' ? v : null;
}

function scale() {
  const vals = rows().map(valueOf).filter((v) => v !== null);
  const min = Math.min(...vals), max = Math.max(...vals);
  return { min, max, span: max - min || 1 };
}

function colorOf(row) {
  const v = valueOf(row);
  if (v === null) return '#e9ecef';
  const { min, span } = scale();
  const i = Math.min(RAMP.length - 1, Math.floor(((v - min) / span) * RAMP.length));
  return RAMP[i];
}

function fmt(v, unit) {
  if (v === null || v === undefined) return '—';
  const n = unit === '명' ? v.toLocaleString('ko-KR') : v;
  return `${n}${unit ? ' ' + unit : ''}`;
}

/* -------------------------------------------------------------- 상단 배너 */

function renderBanner() {
  const p = store.boundary._provenance;
  if (!p || p === 'verified') return;
  const el = $('provenance-banner');
  el.hidden = false;
  el.innerHTML =
    '<strong>경계 데이터 출처 미확인</strong> — 이 지도의 읍면 경계는 다운로드 ' +
    '이력이 기록되지 않은 파일입니다. SGIS에서 재취득해 대조하기 전까지 ' +
    '경계 자체를 검증된 자료로 인용하지 마세요. ' +
    '(<code>data/raw/boundary-eupmyeon-2025-06-30/_meta.json</code>)';
}

function renderSubtitle() {
  const ref = store.regions.meta.reference_dates[state.period];
  const ind = indicatorById(state.indicator);
  // 시설·SGIS 지표는 인구 시점과 기준일이 다르다
  const indRef = ind.reference ? ` (지표 기준 ${ind.reference})` : '';
  $('subtitle').textContent =
    `기준시점 ${ref} · 표시 지표: ${ind.label}${indRef} · 읍면 8개 · ` +
    `생성 ${store.regions.meta.generated_at}`;
}

/* ---------------------------------------------------------------- 사이드 */

function renderPeriods() {
  const box = $('period-tabs');
  box.innerHTML = '';
  store.regions.meta.periods.forEach((p) => {
    const b = document.createElement('button');
    b.textContent = p;
    b.setAttribute('aria-pressed', String(p === state.period));
    b.onclick = () => { state.period = p; redraw(); };
    box.appendChild(b);
  });
}

function renderIndicators() {
  const ul = $('indicator-list');
  ul.innerHTML = '';
  store.regions.indicators.forEach((ind) => {
    const li = document.createElement('li');
    const b = document.createElement('button');
    const available = ind.status === 'available';

    b.disabled = !available;
    b.setAttribute('aria-pressed', String(ind.id === state.indicator));
    const hids = store.hypotheses.hypotheses
      .filter((h) => h.indicator === ind.id).map((h) => h.id).join(' ');
    b.innerHTML =
      `${ind.label}${hids ? `<span class="hyp-mark">${hids}</span>` : ''}<span class="badge">${
        available ? ind.unit : ind.status === 'blocked' ? '보류' : '미확보'
      }</span>`;

    if (!available) {
      const why = document.createElement('span');
      why.className = 'why';
      why.textContent = ind.reason
        ? ind.reason
        : `원자료 미확보 (${ind.blocked_by})`;
      b.appendChild(why);
    }
    b.onclick = () => { state.indicator = ind.id; redraw(); };
    li.appendChild(b);
    ul.appendChild(li);
  });
}

function renderRanking() {
  const ind = indicatorById(state.indicator);
  const ol = $('ranking');
  ol.innerHTML = '';
  const { min, span } = scale();
  const sorted = [...rows()].sort((a, b) => (valueOf(b) ?? -1) - (valueOf(a) ?? -1));

  sorted.forEach((r) => {
    const v = valueOf(r);
    const li = document.createElement('li');
    li.setAttribute('aria-current', String(r.region_code === state.selected));
    li.onclick = () => select(r.region_code, true);
    li.innerHTML =
      `<span style="flex:0 0 72px">${r.region_name || r.name}</span>` +
      `<span class="bar"><span style="width:${
        v === null ? 0 : Math.max(4, ((v - min) / span) * 100)
      }%;background:${colorOf(r)}"></span></span>` +
      `<span class="val">${fmt(v, ind.unit)}</span>`;
    ol.appendChild(li);
  });
}

function renderDetail() {
  const card = $('detail-card');
  if (!state.selected) { card.hidden = true; return; }
  const r = rowByCode(state.selected);
  if (!r) { card.hidden = true; return; }
  card.hidden = false;

  const nearby = store.parks.parks.filter(
    (p) => p.address && p.address.includes(r.name));
  const potholes = store.potholes.points.filter(
    (p) => p.region_code === r.region_code);

  $('detail').innerHTML =
    `<div class="name">${r.name}</div>` +
    '<dl>' +
    `<dt>총인구</dt><dd>${r.population.toLocaleString('ko-KR')} 명</dd>` +
    `<dt>65세 이상</dt><dd>${r.elderly.toLocaleString('ko-KR')} 명</dd>` +
    `<dt>고령화율</dt><dd>${r.elderly_ratio} %</dd>` +
    `<dt>노령화지수</dt><dd>${r.aging_index}</dd>` +
    `<dt>경로당</dt><dd>${r.senior_center_count} 개소 (노후 ${r.senior_center_old_count}, ${r.senior_center_old_ratio}%)</dd>` +
    `<dt>고령 1천명당 경로당</dt><dd>${r.senior_center_per_1k_elderly} 개소</dd>` +
    `<dt>위험지정 세천</dt><dd>${r.drainage_risk_count} 개소</dd>` +
    `<dt>상수도보급률</dt><dd>${r.water_supply_rate} %</dd>` +
    `<dt>도시공원</dt><dd>${nearby.length} 건</dd>` +
    `<dt>포트홀 민원</dt><dd>${potholes.length} 건</dd>` +
    `<dt>행정기관코드</dt><dd>${r.region_code}</dd>` +
    '</dl>' +
    '<p class="why" style="margin:10px 0 0;color:#9ca3af;font-size:11px">' +
    '민원 지표는 원자료 미확보로 표시하지 않습니다.</p>';
}

/* ------------------------------------------------------------- 가설 */

// data/hypotheses.json 이 원본이다. 여기서 문구를 고치지 말 것
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function renderHypothesis() {
  const box = $('hypothesis');
  box.innerHTML = '';
  const list = store.hypotheses.hypotheses.filter((h) => h.indicator === state.indicator);
  if (!list.length) {
    // 가설이 없는 지표(총인구 등)를 보고 있어도 가설 전체가 보이게 목록을 띄운다
    box.appendChild(el('p', 'why', '이 지표에는 연결된 가설이 없습니다. 가설이 있는 지표:'));
    const ul = el('ul', 'hyp-index');
    store.hypotheses.hypotheses.forEach((h) => {
      const li = el('li');
      const b = el('button', null, `${h.id} · ${indicatorById(h.indicator).label}`);
      b.title = h.statement;
      b.onclick = () => { state.indicator = h.indicator; redraw(); };
      li.appendChild(b);
      li.appendChild(el('span', 'why', ` ${h.statement}`));
      ul.appendChild(li);
    });
    box.appendChild(ul);
  }
  list.forEach((h) => {
    const wrap = el('div', 'hyp');
    const head = el('div', 'hyp-head');
    head.appendChild(el('span', 'hyp-id', h.id));
    head.appendChild(el('span', 'hyp-tag', `${h.type} · 방향 ${h.direction}`));
    head.appendChild(el('span', 'st st-partial', h.status));
    wrap.appendChild(head);
    wrap.appendChild(el('p', 'hyp-statement', h.statement));
    const dl = el('dl');
    [['민원 분야', h.complaint_fields.join(', ')], ['근거', h.mechanism],
     ['주의', h.caveat], ['검증 방법', h.verify_method],
     ['검증 자료', h.verify_with.join(', ')]].forEach(([k, v]) => {
      dl.appendChild(el('dt', null, k));
      dl.appendChild(el('dd', null, v));
    });
    wrap.appendChild(dl);
    box.appendChild(wrap);
  });
  const ev = el('details', 'hyp-evidence');
  ev.appendChild(el('summary', null, '참고 사실 (군 단위·표본 부족)'));
  store.hypotheses.evidence.forEach((e) => ev.appendChild(el('p', null, `${e.id} · ${e.text}`)));
  box.appendChild(ev);
}

/* ---------------------------------------------------------- 사분면 */

// 두 지표를 8개 읍면의 중앙값으로 나눠 위치만 보여 준다. 점수·가중치 없음
function median(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length / 2;
  return s.length % 2 ? s[Math.floor(m)] : (s[m - 1] + s[m]) / 2;
}

function renderQuadrant() {
  const v = store.hypotheses.views.find((x) => x.kind === 'quadrant');
  const box = $('quadrant');
  if (!v) { $('quadrant-card').hidden = true; return; }
  const ix = indicatorById(v.x), iy = indicatorById(v.y);
  $('quadrant-title').textContent = `사분면 · ${v.title}`;

  const pts = rows().map((r) => ({ code: r.region_code, name: r.name, x: r[v.x], y: r[v.y] }));
  const mx = median(pts.map((p) => p.x)), my = median(pts.map((p) => p.y));
  const W = 320, H = 300, L = 40, R = 12, T = 12, B = 34;
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const pad = (lo, hi) => { const d = (hi - lo) * 0.12 || 1; return [lo - d, hi + d]; };
  const [x0, x1] = pad(Math.min(...xs), Math.max(...xs));
  const [y0, y1] = pad(Math.min(...ys), Math.max(...ys));
  const sx = (x) => L + ((x - x0) / (x1 - x0)) * (W - L - R);
  const sy = (y) => H - B - ((y - y0) / (y1 - y0)) * (H - T - B);

  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('class', 'quad');
  const add = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, val]) => n.setAttribute(k, val));
    if (text !== undefined) n.textContent = text;
    svg.appendChild(n);
    return n;
  };
  // 오른쪽 위 = 두 지표 모두 중앙값보다 높음
  add('rect', { x: sx(mx), y: T, width: W - R - sx(mx), height: sy(my) - T, class: 'qhh' });
  add('line', { x1: sx(mx), x2: sx(mx), y1: T, y2: H - B, class: 'qmid' });
  add('line', { x1: L, x2: W - R, y1: sy(my), y2: sy(my), class: 'qmid' });
  add('text', { x: (L + W - R) / 2, y: H - 6, 'text-anchor': 'middle', class: 'qaxis' },
      `${ix.label} (${ix.unit}) →`);
  add('text', { x: 10, y: (T + H - B) / 2, 'text-anchor': 'middle', class: 'qaxis',
                transform: `rotate(-90 10 ${(T + H - B) / 2})` }, `${iy.label} (${iy.unit}) →`);
  // 점이 몰린 곳에서 이름이 겹치지 않게 후보 위치 중 빈 곳에 붙인다
  const placed = [];
  const placeLabel = (name, x, y) => {
    const w = name.length * 10 + 4, h = 11;
    const tries = [[8, 4, 'start'], [8, -7, 'start'], [8, 15, 'start'],
                   [-8, 4, 'end'], [-8, -7, 'end'], [-8, 15, 'end'], [0, -10, 'middle']];
    let pick = tries[0];
    for (const t of tries) {
      const [dx, dy, anchor] = t;
      const left = anchor === 'start' ? x + dx : anchor === 'end' ? x + dx - w : x - w / 2;
      const box = [left, y + dy - h + 2, left + w, y + dy + 2];
      const fits = box[0] >= 0 && box[2] <= W && box[1] >= 0 && box[3] <= H &&
        placed.every((b) => box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]);
      if (fits) { pick = t; placed.push(box); break; }
    }
    add('text', { x: x + pick[0], y: y + pick[1], 'text-anchor': pick[2], class: 'qname' }, name);
  };
  pts.forEach((p) => {
    const hh = p.x > mx && p.y > my;
    const c = add('circle', { cx: sx(p.x), cy: sy(p.y), r: p.code === state.selected ? 7 : 5,
                              class: hh ? 'qpt qpt-hh' : 'qpt' });
    c.addEventListener('click', () => select(p.code, true));
    const tip = document.createElementNS(ns, 'title');
    tip.textContent = `${p.name}: ${ix.label} ${p.x}${ix.unit}, ${iy.label} ${p.y}${iy.unit}`;
    c.appendChild(tip);
    placeLabel(p.name, sx(p.x), sy(p.y));
  });

  box.innerHTML = '';
  box.appendChild(svg);
  box.appendChild(el('p', 'qcap',
    `빨간 점 = 두 지표 모두 중앙값보다 높음(${v.high_high_label}). 점선 = 8개 읍면 중앙값 (${ix.label} ${mx.toFixed(1)}${ix.unit}, ${iy.label} ` +
    `${my.toFixed(1)}${iy.unit}). 위치 표시일 뿐 종합 우선순위가 아닙니다. ` +
    `관련 가설: ${v.hypotheses.join(', ')}`));
}

function renderLegend() {
  const ind = indicatorById(state.indicator);
  const { min, max } = scale();
  const step = (max - min) / RAMP.length;
  const parts = RAMP.map((c, i) => {
    const lo = min + step * i;
    const hi = i === RAMP.length - 1 ? max : min + step * (i + 1);
    const round = (x) => (ind.unit === '명' ? Math.round(x).toLocaleString('ko-KR')
                                            : x.toFixed(1));
    return `<span><span class="swatch" style="background:${c}"></span>` +
           `${round(lo)}–${round(hi)}</span>`;
  });
  $('legend').innerHTML =
    parts.join('') +
    `<span style="flex-basis:100%">· ${ind.label} (${ind.unit}) — ` +
    '구간은 현재 화면의 8개 값에 대한 상대 척도입니다(절대 기준이 아님).</span>';
}

function renderSources() {
  const ul = $('sources');
  ul.innerHTML = '';
  const cls = (s) => s === '확보' ? 'st-ok'
    : s === '미확보' || s === '출처미확인' ? 'st-missing' : 'st-partial';

  const list = store.sources.sources.filter((s) => {
    if (state.sourceFilter === 'all') return true;
    if (state.sourceFilter === 'missing') return s.status === '미확보' || s.status === '출처미확인';
    return s.status.startsWith('확보') || s.status === '부분확보';
  });

  list.forEach((s) => {
    const li = document.createElement('li');
    const link = s.url
      ? `<a href="${s.url}" target="_blank" rel="noopener">출처</a>`
      : '<span style="color:#9ca3af">링크 없음</span>';
    li.innerHTML =
      `<div><strong>${s.name}</strong>` +
      `<span class="st ${cls(s.status)}">${s.status}</span></div>` +
      `<div class="meta">${s.provider} · 기준 ${s.reference_date || '미정'} · ` +
      `라이선스: ${s.license} · ${link}</div>` +
      `<div class="meta">${s.notes || ''}</div>`;
    ul.appendChild(li);
  });
}

function renderSourceFilters() {
  const box = $('source-filters');
  box.innerHTML = '';
  [['all', '전체'], ['have', '확보'], ['missing', '미확보']].forEach(([k, label]) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.setAttribute('aria-pressed', String(k === state.sourceFilter));
    b.onclick = () => { state.sourceFilter = k; renderSourceFilters(); renderSources(); };
    box.appendChild(b);
  });
}

/* ------------------------------------------------------------------ 지도 */

function styleFor(feature) {
  const row = rowByCode(feature.properties.region_code);
  return {
    fillColor: row ? colorOf(row) : '#e9ecef',
    fillOpacity: 0.85,
    color: '#ffffff',
    weight: feature.properties.region_code === state.selected ? 3 : 1.5,
  };
}

function initMap() {
  map = L.map('map', { zoomControl: true, attributionControl: true });

  layer = L.geoJSON(store.boundary, {
    style: styleFor,
    onEachFeature: (feature, lyr) => {
      lyr.on('click', () => select(feature.properties.region_code, false));
    },
  });

  // 뷰(center/zoom)를 먼저 잡은 뒤에 레이어를 올린다.
  // 순서가 뒤바뀌면 Leaflet 이 center 없이 투영을 시도해 NaN LatLng 로 터진다.
  map.fitBounds(layer.getBounds(), { padding: [12, 12] });
  layer.addTo(map);

  labels = L.layerGroup(
    layer.getLayers().map((lyr) => {
      const name = lyr.feature.properties.region_name;
      return L.marker(lyr.getBounds().getCenter(), {
        interactive: false,
        icon: L.divIcon({ className: 'area-label', html: name }),
      });
    })
  ).addTo(map);

  const parkLayer = L.layerGroup(
    store.parks.parks.map((p) =>
      L.circleMarker([p.lat, p.lon], {
        radius: 5, color: '#1e6b33', fillColor: '#34a853',
        fillOpacity: 0.9, weight: 1.5,
      }).bindTooltip(`${p.name} (${p.category})`))
  );

  const [from, to] = store.potholes.period;
  const potholeLayer = L.layerGroup(
    store.potholes.points.map((p) =>
      L.circleMarker([p.lat, p.lon], {
        radius: 6, color: '#7a2e0e', fillColor: '#f97316',
        fillOpacity: 0.9, weight: 1.5,
      }).bindTooltip(`포트홀 민원 · ${p.date} · ${p.region_name}`))
  ).addTo(map);

  const sc = store.facilities.senior_centers;
  const seniorLayer = L.layerGroup(
    sc.points.map((p) =>
      L.circleMarker([p.lat, p.lon], {
        radius: 4, color: '#4c1d95', weight: 1,
        // 노후(임시 기준) 경로당은 진하게
        fillColor: p.built_year < sc.old_before_year ? '#7c3aed' : '#c4b5fd',
        fillOpacity: 0.9,
      }).bindTooltip(`경로당 · ${p.name} · ${p.built_year}년 건립`))
  );

  const dr = store.facilities.drainage_risk;
  const drainageLayer = L.layerGroup(
    dr.points.map((p) =>
      L.circleMarker([p.lat, p.lon], {
        radius: 6, color: '#0c4a6e', fillColor: '#0ea5e9',
        fillOpacity: 0.9, weight: 1.5,
      }).bindTooltip(`위험지정 세천 · ${p.name} · ${p.designated_on} 지정`))
  );

  L.control.layers(null, {
    '읍면 이름': labels,
    [`경로당 ${sc.points.length}곳 (진한 색: ${sc.old_before_year}년 이전 건립)`]: seniorLayer,
    [`위험지정 세천 ${dr.points.length}곳 (${dr.reference_date})`]: drainageLayer,
    '도시공원 3건': parkLayer,
    [`포트홀 민원 ${store.potholes.points.length}건 (${from}~${to})`]: potholeLayer,
    '가로등·보안등 (미확보)': L.layerGroup(),
    '상·하수도 관망 (미확보)': L.layerGroup(),
    '민원 발생지점 (미확보)': L.layerGroup(),
  }, { collapsed: false }).addTo(map);
}

function select(code, fromList) {
  state.selected = state.selected === code ? null : code;
  layer.setStyle(styleFor);
  renderRanking();
  renderDetail();
  renderQuadrant();
  if (!fromList && state.selected) {
    const lyr = layer.getLayers().find(
      (l) => l.feature.properties.region_code === state.selected);
    if (lyr) map.fitBounds(lyr.getBounds(), { padding: [40, 40] });
  }
}

/* ------------------------------------------------------------------ 구동 */

function redraw() {
  renderSubtitle();
  renderPeriods();
  renderIndicators();
  renderLegend();
  renderRanking();
  renderDetail();
  renderHypothesis();
  renderQuadrant();
  if (layer) layer.setStyle(styleFor);
}

async function main() {
  const [regions, boundary, parks, potholes, facilities, sources, hypotheses] = await Promise.all([
    getJSON('./data/regions.json'),
    getJSON('./data/eupmyeon.geojson'),
    getJSON('./data/parks.json'),
    getJSON('./data/potholes.json'),
    getJSON('./data/facilities.json'),
    getJSON('./data/sources.json'),
    getJSON('./data/hypotheses.json'),
  ]);
  Object.assign(store, { regions, boundary, parks, potholes, facilities, sources, hypotheses });

  if (boundary.features.length !== 8) {
    throw new Error(`읍면 경계가 8개가 아님: ${boundary.features.length}`);
  }
  const missing = boundary.features
    .map((f) => f.properties.region_code)
    .filter((c) => !regions.regions[regions.meta.default_period]
      .some((r) => r.region_code === c));
  if (missing.length) {
    throw new Error(`데이터에 없는 경계 코드: ${missing.join(', ')}`);
  }

  state.period = regions.meta.default_period;
  // 처음 화면은 가설(H1)이 붙은 지표로 연다 - 가설 카드가 바로 보이게
  const firstHyp = hypotheses.hypotheses[0];
  state.indicator = firstHyp && regions.indicators.some(
    (i) => i.id === firstHyp.indicator && i.status === 'available')
    ? firstHyp.indicator
    : regions.indicators.find((i) => i.status === 'available').id;

  renderBanner();
  initMap();
  renderSourceFilters();
  renderSources();
  redraw();
}

main().catch((err) => {
  document.body.insertAdjacentHTML('afterbegin',
    `<div id="provenance-banner" style="background:#fdecec;border-color:#e0a0a0;
     color:#9b2c2c">데이터를 불러오지 못했습니다: ${err.message}<br>
     <code>python tools/build.py</code> 를 먼저 실행했는지 확인하세요.</div>`);
  console.error(err);
});
