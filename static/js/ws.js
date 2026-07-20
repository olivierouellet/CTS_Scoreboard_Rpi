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
 */
function tremplinSocket(path) {
    var handlers = {};
    var ws = null;
    var closed = false;
    var delay = 500;
    var MAX_DELAY = 5000;
    var queue = [];

    function url() {
        var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return proto + '//' + location.host + path;
    }

    function fire(event, data) {
        (handlers[event] || []).forEach(function (cb) {
            try { cb(data); } catch (e) { console.error(e); }
        });
    }

    function connect() {
        ws = new WebSocket(url());
        ws.onopen = function () {
            delay = 500;
            var pending = queue; queue = [];
            pending.forEach(function (f) { try { ws.send(f); } catch (e) {} });
            fire('connect');
        };
        ws.onmessage = function (ev) {
            var msg;
            try { msg = JSON.parse(ev.data); } catch (e) { return; }
            fire(msg.event, msg.data);
        };
        ws.onclose = function () {
            fire('disconnect');
            if (!closed) {
                setTimeout(connect, delay);
                delay = Math.min(delay * 2, MAX_DELAY);
            }
        };
        ws.onerror = function () { try { ws.close(); } catch (e) {} };
    }

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
        close: function () { closed = true; if (ws) ws.close(); }
    };
    Object.defineProperty(api, 'connected', {
        get: function () { return !!ws && ws.readyState === WebSocket.OPEN; }
    });

    // Defer the first connect so synchronous .on(...) registrations land first.
    setTimeout(connect, 0);
    return api;
}
