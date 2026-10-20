/*
 * support.js — lecteur autonome des maquettes Heimdall (*.dc.html).
 *
 * Rend le format des maquettes dans un navigateur ordinaire :
 * {{trous}}, <sc-for>, <sc-if>, <dc-import>, <helmet>, événements onClick/onChange,
 * classe Component extends DCLogic (props, state, setState).
 *
 * À servir en HTTP (dc-import charge les fichiers voisins) :
 *   cd heimdall-refonte/maquettes && python3 -m http.server 8000
 *   puis http://localhost:8000/Main.dc.html
 * Paramètres d'URL : ?theme=Clair (ou toute autre prop déclarée dans data-props).
 */
(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var HOLE = /\{\{\s*([^}]+?)\s*\}\}/g;
  var WHOLE = /^\s*\{\{\s*([^}]+?)\s*\}\}\s*$/;

  function DCLogic(props) {
    this.props = props || {};
    this.state = {};
  }
  DCLogic.prototype.setState = function (patch) {
    var next = typeof patch === 'function' ? patch(this.state, this.props) : patch;
    this.state = Object.assign({}, this.state, next);
    if (this.__rerender) this.__rerender();
  };
  DCLogic.prototype.forceUpdate = function () {
    if (this.__rerender) this.__rerender();
  };
  window.DCLogic = DCLogic;

  function lookup(scope, path) {
    path = path.trim();
    if (path === 'true') return true;
    if (path === 'false') return false;
    if (path === 'null') return null;
    if (/^-?\d+(\.\d+)?$/.test(path)) return Number(path);
    if (/^(['"]).*\1$/.test(path)) return path.slice(1, -1);
    return path.split('.').reduce(function (o, k) {
      return o == null ? undefined : o[k];
    }, scope);
  }

  function interp(str, scope) {
    var m = str.match(WHOLE);
    if (m) return lookup(scope, m[1]);
    return str.replace(HOLE, function (_, p) {
      var v = lookup(scope, p);
      return v == null ? '' : String(v);
    });
  }

  function camel(name) {
    return name.replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); });
  }

  var helmetsDone = {};
  function injectHelmet(tpl, key) {
    if (helmetsDone[key]) return;
    helmetsDone[key] = true;
    var h = tpl.querySelector('helmet');
    if (!h) return;
    Array.prototype.forEach.call(h.children, function (c) {
      document.head.appendChild(c.cloneNode(true));
    });
  }

  function compile(scriptEl) {
    var decl = {};
    try { decl = JSON.parse(scriptEl.getAttribute('data-props') || '{}'); } catch (e) { console.error('data-props illisible', e); }
    var Cls = new Function('DCLogic', scriptEl.textContent + '\n;return Component;')(DCLogic);
    return { Cls: Cls, decl: decl };
  }

  var cache = {};
  function load(file) {
    if (!cache[file]) {
      cache[file] = fetch(file).then(function (r) {
        if (!r.ok) throw new Error(file + ' : HTTP ' + r.status);
        return r.text();
      }).then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var c = compile(doc.querySelector('script[data-dc-script]'));
        return { tpl: doc.querySelector('x-dc'), Cls: c.Cls, decl: c.decl };
      });
    }
    return cache[file];
  }

  function renderChildren(parent, scope, out) {
    Array.prototype.forEach.call(parent.childNodes, function (n) { renderNode(n, scope, out); });
  }

  function renderNode(n, scope, out) {
    if (n.nodeType === 3) {
      var t = interp(n.textContent, scope);
      out.appendChild(document.createTextNode(t == null ? '' : String(t)));
      return;
    }
    if (n.nodeType !== 1) return;
    var tag = n.localName;

    if (tag === 'helmet') return;
    if (tag === 'sc-for') {
      var list = interp(n.getAttribute('list') || '', scope) || [];
      var as = n.getAttribute('as') || 'item';
      list.forEach(function (it, i) {
        var s = Object.create(scope);
        s[as] = it;
        s.$index = i;
        renderChildren(n, s, out);
      });
      return;
    }
    if (tag === 'sc-if') {
      if (interp(n.getAttribute('value') || '', scope)) renderChildren(n, scope, out);
      return;
    }
    if (tag === 'dc-import') {
      var holder = document.createElement('div');
      holder.style.display = 'contents';
      out.appendChild(holder);
      var props = {};
      Array.prototype.forEach.call(n.attributes, function (a) {
        if (a.name === 'name' || a.name.indexOf('hint-') === 0) return;
        props[camel(a.name)] = interp(a.value, scope);
      });
      mount(n.getAttribute('name') + '.dc.html', holder, props);
      return;
    }

    var inSvg = tag === 'svg' || (out.namespaceURI === SVG_NS);
    var el = inSvg ? document.createElementNS(SVG_NS, tag) : document.createElement(tag);
    Array.prototype.forEach.call(n.attributes, function (a) {
      var name = a.name;
      var v = interp(a.value, scope);
      if (/^on[a-z]+$/i.test(name)) {
        if (typeof v === 'function') {
          var ev = name.slice(2).toLowerCase();
          if (ev === 'change' && (tag === 'input' || tag === 'textarea')) ev = 'input';
          el.addEventListener(ev, v);
        }
        return;
      }
      if (name === 'value' && (tag === 'input' || tag === 'textarea')) {
        el.value = v == null ? '' : v;
        el.setAttribute('value', v == null ? '' : v);
        return;
      }
      if (v === false || v == null) return;
      el.setAttribute(name, v === true ? '' : v);
    });
    renderChildren(n, scope, el);
    out.appendChild(el);
  }

  function snapshotFocus(holder) {
    var a = document.activeElement;
    if (!a || !holder.contains(a) || !a.matches('input, textarea, select')) return null;
    return { sel: a.tagName.toLowerCase() + (a.getAttribute('placeholder') ? '[placeholder="' + a.getAttribute('placeholder').replace(/"/g, '\\"') + '"]' : ''), start: a.selectionStart, end: a.selectionEnd };
  }
  function restoreFocus(holder, f) {
    if (!f) return;
    var el = holder.querySelector(f.sel);
    if (!el) return;
    el.focus();
    try { el.setSelectionRange(f.start, f.end); } catch (e) {}
  }

  function instantiate(tpl, Cls, decl, props, holder, key) {
    var p = {};
    Object.keys(decl).forEach(function (k) {
      if (k.charAt(0) !== '$' && decl[k] && Object.prototype.hasOwnProperty.call(decl[k], 'default')) p[k] = decl[k]['default'];
    });
    Object.assign(p, props);
    var inst = new Cls(p);
    if (!inst.state) inst.state = {};
    injectHelmet(tpl, key);
    var render = function () {
      var f = snapshotFocus(holder);
      holder.innerHTML = '';
      var vals = inst.renderVals ? inst.renderVals() : {};
      renderChildren(tpl, vals, holder);
      restoreFocus(holder, f);
    };
    inst.__rerender = render;
    render();
    if (inst.componentDidMount) inst.componentDidMount();
  }

  function mount(file, holder, props) {
    return load(file).then(function (c) {
      instantiate(c.tpl, c.Cls, c.decl, props, holder, file);
    }).catch(function (e) {
      holder.textContent = 'Impossible de charger ' + file + ' (servez le dossier en HTTP : python3 -m http.server).';
      console.error(e);
    });
  }

  function boot() {
    var tpl = document.querySelector('x-dc');
    var script = document.querySelector('script[data-dc-script]');
    if (!tpl || !script) return;
    var c = compile(script);
    var props = {};
    new URLSearchParams(location.search).forEach(function (v, k) { props[k] = v; });
    var holder = document.createElement('div');
    tpl.parentNode.insertBefore(holder, tpl);
    tpl.remove();
    instantiate(tpl, c.Cls, c.decl, props, holder, location.pathname);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
