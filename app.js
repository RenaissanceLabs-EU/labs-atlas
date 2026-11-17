/* Open Labs Atlas — map, filters and mini maps. No innerHTML with data; everything via textContent. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var TYPES = { startup: 'Independent company', nonprofit: 'Nonprofit', collective: 'Community collective', institute: 'Institute', academic: 'Academic lab' };

  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  Promise.all([
    fetch('/data/labs.json').then(function (r) { return r.json(); }),
    fetch('/assets/vendor/countries-110m.json').then(function (r) { return r.json(); })
  ]).then(function (res) {
    var labs = res[0].labs;
    var world = res[1];
    var land = topojson.feature(world, world.objects.land);
    var borders = topojson.mesh(world, world.objects.countries, function (a, b) { return a !== b; });
    var root = document.querySelector('[data-lab-page]');
    if (root) { tocSpy(); return miniMap(labs, land, borders, root.getAttribute('data-lab-page')); }
    if (document.getElementById('map')) bigMap(labs, land, borders);
  }).catch(function (e) { console.error('atlas failed', e); });

  /* ---------- lab page: highlight current section in the contents list ---------- */
  function tocSpy() {
    var links = Array.prototype.slice.call(document.querySelectorAll('.toc a'));
    if (!links.length || !('IntersectionObserver' in window)) return;
    var map = {};
    links.forEach(function (a) { map[a.getAttribute('href').slice(1)] = a; });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { links.forEach(function (a) { a.classList.remove('on'); }); var a = map[e.target.id]; if (a) a.classList.add('on'); }
      });
    }, { rootMargin: '-20% 0px -65% 0px' });
    Object.keys(map).forEach(function (id) { var s = document.getElementById(id); if (s) io.observe(s); });
  }

  /* ---------- lab page mini map ---------- */
  function miniMap(labs, land, borders, id) {
    var host = document.getElementById('mini');
    var lab = labs.find(function (l) { return l.id === id; });
    if (!host || !lab) return;
    var w = 400, hgt = 250;
    var svg = el('svg', { viewBox: '0 0 ' + w + ' ' + hgt, role: 'img', 'aria-label': 'Location of ' + lab.name }, host);
    var proj = d3.geoMercator().center([lab.lon, lab.lat]).scale(w * 1.1).translate([w / 2, hgt / 2]);
    var path = d3.geoPath(proj);
    el('path', { d: path(land), fill: '#efe6d2' }, svg);
    el('path', { d: path(borders), fill: 'none', stroke: '#fdfaf3', 'stroke-width': 0.8 }, svg);
    labs.forEach(function (l) {
      if (l.id === id) return;
      var p = proj([l.lon, l.lat]);
      if (!p || p[0] < 0 || p[0] > w || p[1] < 0 || p[1] > hgt) return;
      var a = el('a', { href: '/labs/' + l.id + '/' }, svg);
      el('circle', { cx: p[0], cy: p[1], r: 4, fill: '#c79a3f', stroke: '#fffaf0', 'stroke-width': 1, opacity: 0.8 }, a).appendChild(Object.assign(el('title', {}), { textContent: l.name }));
    });
    var c = proj([lab.lon, lab.lat]);
    el('circle', { cx: c[0], cy: c[1], r: 16, fill: 'rgba(246,196,83,.35)' }, svg);
    el('circle', { cx: c[0], cy: c[1], r: 7, fill: '#9a7a48', stroke: '#fffaf0', 'stroke-width': 2 }, svg);
  }

  /* ---------- big map ---------- */
  function bigMap(labs, land, borders) {
    var host = document.getElementById('map');
    var tip = document.getElementById('tip');
    var peek = document.getElementById('peek');
    var width = 1000, height = 540;
    var svg = el('svg', { viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': 'World map of independent open source AI labs' }, host);
    var g = el('g', {}, svg);
    var proj = d3.geoNaturalEarth1().fitExtent([[8, 8], [width - 8, height - 8]], { type: 'Sphere' });
    var path = d3.geoPath(proj);
    el('path', { d: path({ type: 'Sphere' }), class: 'sea' }, g);
    el('path', { d: path(d3.geoGraticule10()), class: 'graticule' }, g);
    el('path', { d: path(land), class: 'land' }, g);
    el('path', { d: path(borders), class: 'borders' }, g);
    el('path', { d: path(land), class: 'outline' }, g);

    var pinLayer = el('g', {}, g);
    var pins = {};
    var visibleSet = null;
    labs.forEach(function (l, i) {
      var p = proj([l.lon, l.lat]);
      if (!p) return;
      var pin = el('g', { class: 'pin t-' + l.type, transform: 'translate(' + p[0] + ',' + p[1] + ')', tabindex: 0, role: 'link', 'aria-label': l.name + ', ' + l.city + ', ' + l.country }, pinLayer);
      var inner = el('g', { class: 'inner' }, pin);
      el('circle', { class: 'halo', r: 11 }, inner);
      var pu = el('circle', { class: 'pulse', r: 5 }, inner);
      pu.style.animationDelay = ((i * 137) % 3400) + 'ms';
      el('circle', { class: 'dot', r: 4.2 }, inner);
      pin.addEventListener('mouseenter', function () { showTip(l, p); });
      pin.addEventListener('mouseleave', hideTip);
      pin.addEventListener('focus', function () { showTip(l, p); });
      pin.addEventListener('blur', hideTip);
      pin.addEventListener('click', function (e) { e.stopPropagation(); select(l.id, true); });
      pin.addEventListener('keydown', function (e) { if (e.key === 'Enter') select(l.id, true); });
      pins[l.id] = { node: pin, inner: inner, p: p, lab: l };
    });

    var k = 1, tf = d3.zoomIdentity;
    var hintEl = document.getElementById('hint'), hintT = null;
    function hint() { if (!hintEl) return; hintEl.classList.add('show'); clearTimeout(hintT); hintT = setTimeout(function () { hintEl.classList.remove('show'); }, 1400); }
    var zoom = d3.zoom().filter(function (ev) {
      if (ev.type === 'wheel') { if (ev.ctrlKey || ev.metaKey) return true; hint(); return false; }
      if (ev.type && ev.type.indexOf('touch') === 0) return ev.touches && ev.touches.length >= 2;
      return !ev.button;
    }).scaleExtent([1, 40]).translateExtent([[-40, -40], [width + 40, height + 40]]).on('zoom', function (ev) {
      tf = ev.transform; k = tf.k;
      g.setAttribute('transform', tf.toString());
      var s = 1 / Math.sqrt(k);
      for (var id in pins) pins[id].inner.setAttribute('transform', 'scale(' + s + ')');
      hideTip();
      document.querySelectorAll('.land,.borders,.outline,.graticule').forEach(function (n) { n.style.strokeWidth = ''; });
      borderW(k);
    });
    function borderW(kk) { var b = host.querySelector('.borders'); if (b) b.style.strokeWidth = (0.6 / kk) + 'px'; var o = host.querySelector('.outline'); if (o) o.style.strokeWidth = (0.6 / kk) + 'px'; }
    d3.select(svg).call(zoom).on('dblclick.zoom', null);
    svg.addEventListener('click', function () { closePeek(); });

    function px(p) { return tf.apply(p); }
    function showTip(l, p) {
      var q = px(p);
      var pt = svg.createSVGPoint(); pt.x = q[0]; pt.y = q[1];
      var sc = pt.matrixTransform(svg.getScreenCTM()), hr = host.getBoundingClientRect();
      q = [sc.x - hr.left, sc.y - hr.top];
      tip.textContent = '';
      var b = h('b', null, l.name); var s = h('span', null, l.city + ', ' + l.country);
      tip.appendChild(b); tip.appendChild(s);
      tip.style.left = q[0] + 'px'; tip.style.top = q[1] + 'px';
      tip.classList.add('show');
    }
    function hideTip() { tip.classList.remove('show'); }

    function closePeek() { peek.classList.remove('show'); for (var id in pins) pins[id].node.classList.remove('on'); }
    function select(id, fly) {
      var o = pins[id]; if (!o) return;
      var l = o.lab;
      for (var i in pins) pins[i].node.classList.toggle('on', i === id);
      peek.textContent = '';
      var x = h('button', 'x', '×'); x.setAttribute('aria-label', 'Close'); x.addEventListener('click', closePeek);
      var eye = h('div', 'loc'); var bd = h('span', 'badge ' + l.type); eye.appendChild(bd); eye.appendChild(document.createTextNode((TYPES[l.type] || l.type) + ' · ' + l.city + ', ' + l.country));
      eye.style.cssText = 'font-size:12.5px;color:#958c80;letter-spacing:.04em';
      var t = h('h3', null, l.name); var p = h('p', null, l.summary);
      var row = h('div', 'row');
      var a1 = h('a', 'btn small', 'Open lab page'); a1.href = '/labs/' + l.id + '/';
      var a2 = h('a', 'btn small ghost', 'Website'); a2.href = l.website; a2.target = '_blank'; a2.rel = 'noopener';
      row.appendChild(a1); if (l.website) row.appendChild(a2);
      [x, eye, t, p, row].forEach(function (n) { peek.appendChild(n); });
      peek.classList.add('show');
      if (fly) flyTo(o.p, Math.max(k, 5));
      var card = document.querySelector('.card[data-id="' + id + '"]');
      if (card) card.classList.add('flash');
    }
    function flyTo(p, scale) {
      var t = d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-p[0], -p[1]);
      d3.select(svg).transition().duration(900).ease(d3.easeCubicInOut).call(zoom.transform, t);
    }
    function reset() { closePeek(); d3.select(svg).transition().duration(700).call(zoom.transform, d3.zoomIdentity); }
    document.getElementById('zin').addEventListener('click', function () { d3.select(svg).transition().duration(300).call(zoom.scaleBy, 1.8); });
    document.getElementById('zout').addEventListener('click', function () { d3.select(svg).transition().duration(300).call(zoom.scaleBy, 1 / 1.8); });
    document.getElementById('zreset').addEventListener('click', reset);

    /* focus on a region */
    var REGION_VIEW = {
      'Europe': [10, 52, 4.2], 'North America': [-98, 40, 2.4], 'Latin America': [-65, -15, 2.4],
      'Asia': [95, 30, 2.1], 'Middle East': [48, 28, 4], 'Africa': [18, 2, 2.4], 'Oceania': [140, -28, 2.8]
    };
    function focusRegion(r) {
      var v = REGION_VIEW[r];
      if (!v) return reset();
      var p = proj([v[0], v[1]]);
      flyTo(p, v[2]);
    }

    /* ---------- filters ---------- */
    var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
    var q = document.getElementById('q'), typeBtns = document.querySelectorAll('[data-type]'),
      regionSel = document.getElementById('region'), focusSel = document.getElementById('focus'), countEl = document.getElementById('count');
    var state = { q: '', type: 'all', region: 'all', focus: 'all' };
    function apply() {
      var n = 0, term = state.q.trim().toLowerCase();
      cards.forEach(function (c) {
        var ok = (state.type === 'all' || c.dataset.type === state.type) &&
          (state.region === 'all' || c.dataset.region === state.region) &&
          (state.focus === 'all' || (' ' + c.dataset.focus + ' ').indexOf(' ' + state.focus + ' ') > -1 || c.dataset.focus.split('|').indexOf(state.focus) > -1) &&
          (!term || c.dataset.search.indexOf(term) > -1);
        c.hidden = !ok;
        if (ok) n++;
        var pin = pins[c.dataset.id];
        if (pin) pin.node.classList.toggle('dim', !ok);
      });
      countEl.textContent = n + (n === 1 ? ' lab' : ' labs');
      document.getElementById('empty').hidden = n !== 0;
    }
    q.addEventListener('input', function () { state.q = q.value; apply(); });
    typeBtns.forEach(function (b) {
      b.addEventListener('click', function () {
        state.type = b.dataset.type;
        typeBtns.forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
        apply();
      });
    });
    regionSel.addEventListener('change', function () { state.region = regionSel.value; apply(); focusRegion(state.region === 'all' ? null : state.region); });
    focusSel.addEventListener('change', function () { state.focus = focusSel.value; apply(); });
    cards.forEach(function (c) {
      c.addEventListener('mouseenter', function () { var o = pins[c.dataset.id]; if (o) o.node.classList.add('on'); });
      c.addEventListener('mouseleave', function () { var o = pins[c.dataset.id]; if (o && !peek.classList.contains('show')) o.node.classList.remove('on'); });
    });
    document.getElementById('shuffle').addEventListener('click', function () {
      var vis = cards.filter(function (c) { return !c.hidden; });
      if (!vis.length) return;
      var c = vis[Math.floor(Math.random() * vis.length)];
      document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
      select(c.dataset.id, true);
    });
    var hash = location.hash.replace('#', '');
    if (hash && pins[hash]) setTimeout(function () { select(hash, true); }, 300);
    apply();
  }
})();
