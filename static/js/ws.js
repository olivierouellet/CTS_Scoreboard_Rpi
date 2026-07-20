/*
 * tremplinSocket(path) — tiny plain-WebSocket client that replaces socket.io.
 *
 * API mirrors the small slice of socket.io the app used:
 *   var s = tremplinSocket('/ws/scoreboard');
 *   s.on('update_scoreboard', function(data) { ... });
 *   s.emit('set_overlay', { active: true });
 *
 * Messages are JSON frames { "event": <name>, "data": <any> }. The socket
 * reconnects automatically with capped backoff and re-fires the 'connect'
 * handler on every (re)connection — so a handler that emits 'join_meet' on
 * 'connect' transparently rejoins its room after a drop.
 *
 * Robustness (what socket.io/Engine.IO gave us for free): a heartbeat detects
 * silently-dead connections — common on phones after screen-lock, tab-switch, or
 * a Wi-Fi hop, where the socket dies without firing onclose — and reconnects
 * promptly on foreground/online. The server replies to {event:'ping'} with
 * {event:'pong'}; if no frame arrives for STALE_MS the connection is treated as
 * dead and reopened.
 */
function tremplinSocket(path) {
    var handlers = {};
    var ws = null;
    var closed = false;
    var delay = 500;
    var MAX_DELAY = 5000;
    var queue = [];

    var HEARTBEAT_MS = 15000;   // send a ping this often while open
    var STALE_MS     = 35000;   // no inbound frame for this long => assume dead
    var lastRecv = 0;
    var hbTimer = null, watchdog = null, reconnectTimer = null;

    function url() {
        var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return proto + '//' + location.host + path;
    }

    function fire(event, data) {
        (handlers[event] || []).forEach(function (cb) {
            try { cb(data); } catch (e) { console.error(e); }
        });
    }

    function startHeartbeat() {
        stopHeartbeat();
        lastRecv = Date.now();
        hbTimer = setInterval(function () {
            if (ws && ws.readyState === WebSocket.OPEN) {
                try { ws.send(JSON.stringify({ event: 'ping' })); } catch (e) {}
            }
        }, HEARTBEAT_MS);
        watchdog = setInterval(function () {
            if (ws && ws.readyState === WebSocket.OPEN && Date.now() - lastRecv > STALE_MS) {
                try { ws.close(); } catch (e) {}   // silently dead -> onclose -> reconnect
            }
        }, HEARTBEAT_MS);
    }

    function stopHeartbeat() {
        if (hbTimer)   { clearInterval(hbTimer);   hbTimer = null; }
        if (watchdog)  { clearInterval(watchdog);  watchdog = null; }
    }

    function connect() {
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        ws = new WebSocket(url());
        ws.onopen = function () {
            delay = 500;
            var pending = queue; queue = [];
            pending.forEach(function (f) { try { ws.send(f); } catch (e) {} });
            startHeartbeat();
            fire('connect');
        };
        ws.onmessage = function (ev) {
            lastRecv = Date.now();
            var msg;
            try { msg = JSON.parse(ev.data); } catch (e) { return; }
            if (msg.event === 'pong') return;   // heartbeat reply — liveness only
            fire(msg.event, msg.data);
        };
        ws.onclose = function () {
            stopHeartbeat();
            fire('disconnect');
            scheduleReconnect();
        };
        ws.onerror = function () { try { ws.close(); } catch (e) {} };
    }

    function scheduleReconnect() {
        if (closed || reconnectTimer) return;
        reconnectTimer = setTimeout(function () { reconnectTimer = null; connect(); }, delay);
        delay = Math.min(delay * 2, MAX_DELAY);
    }

    // Mobile browsers freeze/drop background sockets without firing onclose; when
    // the tab returns to the foreground (or the network comes back), verify the
    // socket is really alive and reconnect promptly if not.
    function wake() {
        if (closed) return;
        if (ws && ws.readyState === WebSocket.OPEN) {
            var mark = lastRecv;
            try { ws.send(JSON.stringify({ event: 'ping' })); } catch (e) {}
            setTimeout(function () {
                if (!closed && ws && ws.readyState === WebSocket.OPEN && lastRecv === mark) {
                    try { ws.close(); } catch (e) {}   // no pong -> dead -> reconnect
                }
            }, 4000);
        } else if (!ws || ws.readyState === WebSocket.CLOSED) {
            delay = 500;
            connect();
        }
    }
    if (typeof document !== 'undefined')
        document.addEventListener('visibilitychange', function () { if (!document.hidden) wake(); });
    if (typeof window !== 'undefined')
        window.addEventListener('online', wake);

    var api = {
        on: function (event, cb) {
            (handlers[event] = handlers[event] || []).push(cb);
            return api;
        },
        off: function (event, cb) {
            // No event -> drop everything; event only -> drop all its handlers;
            // event + cb -> drop that one. Mirrors socket.io's client .off().
            if (!event) handlers = {};
            else if (!cb) delete handlers[event];
            else if (handlers[event])
                handlers[event] = handlers[event].filter(function (h) { return h !== cb; });
            return api;
        },
        once: function (event, cb) {
            var wrap = function (data) {
                var list = handlers[event] || [];
                var i = list.indexOf(wrap);
                if (i >= 0) list.splice(i, 1);
                cb(data);
            };
            return api.on(event, wrap);
        },
        emit: function (event, data) {
            var frame = JSON.stringify({ event: event, data: data });
            if (ws && ws.readyState === WebSocket.OPEN) ws.send(frame);
            else queue.push(frame);
            return api;
        },
        close: function () {
            closed = true;
            stopHeartbeat();
            if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
            if (ws) ws.close();
        }
    };
    Object.defineProperty(api, 'connected', {
        get: function () { return !!ws && ws.readyState === WebSocket.OPEN; }
    });

    // Defer the first connect so synchronous .on(...) registrations land first.
    setTimeout(connect, 0);
    return api;
}
