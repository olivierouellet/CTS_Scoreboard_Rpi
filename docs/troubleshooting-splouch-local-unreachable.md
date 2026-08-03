# `splouch.local` won't load in the browser (but ping works)

## Symptom

- `ping splouch.local` works.
- Loading `http://splouch.local/` in a browser fails / hangs.
- Connecting to the Pi **by its IP address** works:
  `http://10.8.20.103/` and `http://10.8.20.103:5000/live` both load.

So the Pi, the FastAPI service, and the port-80 redirect are all healthy — only
the **hostname** fails to load.

## Cause

The Pi is multihomed (e.g. WiFi `wlan0` has an IP, `eth0` does not, or vice
versa). avahi advertises **every** address it has for `splouch.local`,
including the **IPv6 link-local** address (`fe80::…`) on the active interface.

When a browser resolves `splouch.local` it receives both an `AAAA`
(IPv6 link-local) and an `A` (IPv4) record. Many browsers/OSes **prefer IPv6**,
try the `fe80::…` address first, and a link-local IPv6 address can't be reached
without a zone index (`%iface`) — so the connection hangs or fails. `ping` and
direct-IP access worked because they used IPv4.

You can spot the IPv6 link-local being published in the avahi log:

```text
avahi-daemon[680]: Registering new address record for fe80::e65f:1ff:fe86:772 on wlan0.*.
```

## Solution

Stop avahi from publishing the IPv6 record, so `splouch.local` only ever
resolves to the reachable IPv4 address. **Two** settings are involved in
`/etc/avahi/avahi-daemon.conf`:

```ini
[server]
use-ipv6=no                 # disables the IPv6 mDNS transport

[publish]
publish-aaaa-on-ipv4=no     # stops the AAAA record being announced over IPv4
```

> ⚠️ `use-ipv6=no` alone is **not enough** — `publish-aaaa-on-ipv4` defaults to
> `yes`, so avahi keeps announcing the `fe80::…` AAAA record over IPv4 even with
> the IPv6 transport disabled. That setting is the actual culprit.

Apply both (handles the "commented", "set", and "missing" cases):

```bash
# use-ipv6=no  (under [server])
if grep -q '^#*[[:space:]]*use-ipv6=' /etc/avahi/avahi-daemon.conf; then
    sudo sed -i 's/^#*[[:space:]]*use-ipv6=.*/use-ipv6=no/' /etc/avahi/avahi-daemon.conf
else
    sudo sed -i '/^\[server\]/a use-ipv6=no' /etc/avahi/avahi-daemon.conf
fi

# publish-aaaa-on-ipv4=no  (under [publish])
if grep -q '^#*[[:space:]]*publish-aaaa-on-ipv4=' /etc/avahi/avahi-daemon.conf; then
    sudo sed -i 's/^#*[[:space:]]*publish-aaaa-on-ipv4=.*/publish-aaaa-on-ipv4=no/' /etc/avahi/avahi-daemon.conf
else
    sudo sed -i '/^\[publish\]/a publish-aaaa-on-ipv4=no' /etc/avahi/avahi-daemon.conf
fi

sudo systemctl restart avahi-daemon
```

Confirm it took — the IPv6 lookup should now fail and only IPv4 should resolve:

```bash
avahi-resolve -n splouch.local -6     # should return nothing
avahi-resolve -n splouch.local        # should return only the IPv4 address
```

Then flush the client's DNS/mDNS cache and reload `http://splouch.local/`:

- **macOS:** `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`
- **Windows:** `ipconfig /flushdns`

> Browsers cache the failed/stale resolution aggressively. If a private/incognito
> window works but a normal window doesn't, the server is fixed — you just need
> to clear the browser cache or fully quit and reopen the browser (on Safari,
> ⌘Q, or Develop → Empty Caches).

## Notes

- This is handled automatically by `install.sh` (in the **mDNS aliases**
  section) for new installs.
- Disabling IPv6 in avahi is safe for this LAN scoreboard use case — all
  clients reach the Pi over IPv4.
- If the page is still unreachable after this and **even direct IP fails from
  the client**, the network has WiFi client/AP isolation enabled (common on
  corporate networks). That blocks device-to-device traffic and can only be
  fixed on the network side, or by connecting clients to the pool-deck `eth0`
  network instead.
