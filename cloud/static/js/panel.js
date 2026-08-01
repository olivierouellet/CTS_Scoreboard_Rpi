/* ============================================================================
   Tremplin operator panels — shared UI behaviour.
   Used by BOTH the Pi server Settings panel and the cloud Admin panel.

   CANONICAL SOURCE: static/js/panel.js
   Keep cloud/static/js/panel.js byte-identical via scripts/sync-ui-assets.sh.
   Loaded after bootstrap.bundle.js and BEFORE each page's own inline <script>
   (so window.panelShowTab / copyKey are defined first).

   Provides:
     - Colour theme toggle (Light / Dark / Auto), key "cts_theme".
     - Sidebar tab switcher window.panelShowTab(target); also dispatches a
       'panel:tab-shown' CustomEvent (detail.target) for optional per-tab init.
     - Press-and-hold confirmation for [data-hold] elements.
     - window.copyKey(btn, text) copy-to-clipboard with feedback.
   The anti-flash pre-paint theme snippet stays inline in each <head>.
   ========================================================================== */
(function () {
    'use strict';

    /* ── Colour theme toggle (Light / Dark / Auto) ── */
    var THEME_KEY = 'cts_theme';
    var mq = matchMedia('(prefers-color-scheme: dark)');
    function applyTheme(pref) {
        var mode = (pref === 'auto') ? (mq.matches ? 'dark' : 'light') : pref;
        document.documentElement.setAttribute('data-bs-theme', mode);
        document.querySelectorAll('[data-theme-set]').forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-theme-set') === pref);
        });
    }
    applyTheme(localStorage.getItem(THEME_KEY) || 'dark');
    document.querySelectorAll('[data-theme-set]').forEach(function (b) {
        b.addEventListener('click', function () {
            var pref = b.getAttribute('data-theme-set');
            localStorage.setItem(THEME_KEY, pref);
            applyTheme(pref);
        });
    });
    mq.addEventListener('change', function () {
        if ((localStorage.getItem(THEME_KEY) || 'dark') === 'auto') applyTheme('auto');
    });

    /* ── Sidebar tab switcher ──
       Activates the target pane and every .tab-pane ancestor (nested panes),
       marks the sidebar link active, expands the collapse group that holds it,
       and dispatches 'panel:tab-shown'. Page-specific per-tab side effects can
       either bind their own click listeners or listen for that event. */
    function showTab(target) {
        var pane = target && document.querySelector(target);
        if (!pane) return;
        document.querySelectorAll('.tab-pane').forEach(function (p) { p.classList.remove('active'); });
        var el = pane;
        while (el) {
            if (el.classList && el.classList.contains('tab-pane')) el.classList.add('active');
            el = el.parentElement;
        }
        document.querySelectorAll('.app-nav .nav-link').forEach(function (a) { a.classList.remove('active'); });
        var link = document.querySelector('.app-nav .nav-link[data-target="' + target + '"]');
        if (link) {
            link.classList.add('active');
            var grp = link.closest('.collapse');
            if (grp && window.bootstrap) bootstrap.Collapse.getOrCreateInstance(grp, { toggle: false }).show();
        }
        document.dispatchEvent(new CustomEvent('panel:tab-shown', { detail: { target: target } }));
    }
    window.panelShowTab = showTab;

    document.querySelectorAll('.app-nav .nav-link[data-target]').forEach(function (link) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            var target = link.getAttribute('data-target');
            showTab(target);
            try { history.replaceState(null, '', target); } catch (_) {}
            var oc = document.getElementById('app-sidebar');
            if (window.bootstrap && oc) {
                var inst = bootstrap.Offcanvas.getInstance(oc);
                if (inst) inst.hide();
            }
        });
    });

    /* ── Press-and-hold confirmation for destructive actions ──
       Any [data-hold] element needs a ~1.2 s press-and-hold instead of a click
       (it fills red as feedback). On completion it runs data-hold-fn (a global
       function name) else navigates to data-hold-href / href. Delegated, so it
       also covers dynamically-added buttons. */
    (function () {
        var HOLD_MS = 1200;
        var active = null, timer = null, origLabel = null;
        function reset(el) {
            el.classList.remove('btn-holding');
            if (origLabel !== null) { el.textContent = origLabel; origLabel = null; }
        }
        function run(el) {
            var fn = el.getAttribute('data-hold-fn');
            var href = el.getAttribute('data-hold-href') || el.getAttribute('href');
            if (fn && typeof window[fn] === 'function') window[fn]();
            else if (href) window.location.href = href;
        }
        function cancel() {
            if (timer) { clearTimeout(timer); timer = null; }
            if (active) { reset(active); active = null; }
        }
        document.addEventListener('click', function (e) {
            if (e.target.closest('[data-hold]')) e.preventDefault();  // no plain-click action
        }, true);
        document.addEventListener('pointerdown', function (e) {
            var el = e.target.closest('[data-hold]');
            if (!el || el.disabled || el.classList.contains('disabled')) return;
            e.preventDefault();
            active = el;
            el.classList.add('btn-holding');
            var lbl = el.getAttribute('data-hold-label');
            if (lbl !== null) { origLabel = el.textContent; el.textContent = lbl; }
            timer = setTimeout(function () {
                timer = null;
                var el2 = active; active = null;
                if (el2) { reset(el2); run(el2); }
            }, HOLD_MS);
        });
        document.addEventListener('pointerup', cancel);
        document.addEventListener('pointercancel', cancel);
        document.addEventListener('pointermove', function (e) {
            if (active && e.target.closest('[data-hold]') !== active) cancel();
        });
    })();

    /* ── Copy to clipboard (with "copied!" feedback) ── */
    window.copyKey = function (btn, text) {
        var orig = btn.textContent;
        var copied = btn.dataset.copied || 'Copied!';
        navigator.clipboard.writeText(text).then(function () {
            btn.textContent = copied; btn.classList.add('copied');
            setTimeout(function () { btn.textContent = orig; btn.classList.remove('copied'); }, 2000);
        });
    };
})();
