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
  $('subtitle').textContent =
    `기준시점 ${ref} · 표시 지표: ${ind.label} · 읍면 8개 · ` +
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
    b.innerHTML =
      `${ind.label}<span class="badge">${
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
    `<dt>도시공원</dt><dd>${nearby.length} 건</dd>` +
    `<dt>포트홀 민원</dt><dd>${potholes.length} 건</dd>` +
    `<dt>행정기관코드</dt><dd>${r.region_code}</dd>` +
    '</dl>' +
    '<p class="why" style="margin:10px 0 0;color:#9ca3af;font-size:11px">' +
    '민원·시설 지표는 원자료 미확보로 표시하지 않습니다.</p>';
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

  L.control.layers(null, {
    '읍면 이름': labels,
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
  if (layer) layer.setStyle(styleFor);
}

async function main() {
  const [regions, boundary, parks, potholes, sources] = await Promise.all([
    getJSON('./data/regions.json'),
    getJSON('./data/eupmyeon.geojson'),
    getJSON('./data/parks.json'),
    getJSON('./data/potholes.json'),
    getJSON('./data/sources.json'),
  ]);
  Object.assign(store, { regions, boundary, parks, potholes, sources });

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
  state.indicator = regions.indicators.find((i) => i.status === 'available').id;

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
