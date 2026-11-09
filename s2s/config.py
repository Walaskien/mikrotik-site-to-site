"""Load and validate the site-to-site YAML input."""
import base64
import binascii
import ipaddress
import re

import yaml

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")


class ConfigError(Exception):
    """Raised with all problems found, one per line."""


def _iface(addr, where, errors, need_gateway=False):
    if not isinstance(addr, dict):
        errors.append("%s: must be a mapping" % where)
        return None
    for key in ("interface", "address") + (("gateway",) if need_gateway else ()):
        if not addr.get(key):
            errors.append("%s: missing '%s'" % (where, key))
    try:
        ifc = ipaddress.ip_interface(addr.get("address", ""))
    except ValueError:
        errors.append("%s: invalid address %r" % (where, addr.get("address")))
        return None
    if need_gateway and addr.get("gateway"):
        try:
            gw = ipaddress.ip_address(addr["gateway"])
        except ValueError:
            errors.append("%s: invalid gateway %r" % (where, addr["gateway"]))
            return None
        if gw not in ifc.network:
            errors.append("%s: gateway %s is outside %s" % (where, gw, ifc.network))
    return ifc


def _key(value, where, errors):
    try:
        ok = len(base64.b64decode(str(value), validate=True)) == 32
    except (binascii.Error, ValueError):
        ok = False
    if not ok:
        errors.append("%s: not a WireGuard public key (base64 of 32 bytes)" % where)


def load(path):
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    return validate(raw)


def validate(raw):
    """Return a normalised config dict or raise ConfigError."""
    errors = []
    if not isinstance(raw, dict):
        raise ConfigError("top level must be a mapping")

    t = raw.get("tunnel") or {}
    tunnel = {"mtu": int(t.get("mtu", 1420)),
              "primary_port": int(t.get("primary_port", 13231)),
              "backup_port": int(t.get("backup_port", 13232))}
    for kind in ("primary", "backup"):
        try:
            tunnel[kind + "_subnet"] = ipaddress.ip_network(t.get(kind + "_subnet"))
        except (ValueError, TypeError):
            errors.append("tunnel.%s_subnet: missing or invalid" % kind)
    if not 1280 <= tunnel["mtu"] <= 1500:
        errors.append("tunnel.mtu: must be between 1280 and 1500")
    if tunnel["primary_port"] == tunnel["backup_port"]:
        errors.append("tunnel: primary_port and backup_port must differ")

    mgmt = []
    for s in raw.get("management_sources") or []:
        try:
            mgmt.append(str(ipaddress.ip_network(s)))
        except ValueError:
            errors.append("management_sources: invalid network %r" % s)

    sites, names, ids = [], set(), set()
    raw_sites = raw.get("sites")
    if not isinstance(raw_sites, list) or len(raw_sites) < 2:
        errors.append("sites: need a list of at least two sites")
        raw_sites = []
    for i, s in enumerate(raw_sites):
        name = s.get("name", "")
        where = "sites[%d] (%s)" % (i, name)
        if not NAME_RE.match(str(name)):
            errors.append("%s: name must match %s" % (where, NAME_RE.pattern))
        if name in names:
            errors.append("%s: duplicate name" % where)
        names.add(name)
        sid = s.get("id")
        if not isinstance(sid, int) or not 1 <= sid <= 250:
            errors.append("%s: id must be an integer 1..250" % where)
        elif sid in ids:
            errors.append("%s: duplicate id %s" % (where, sid))
        ids.add(sid)
        lan = _iface(s.get("lan"), where + ".lan", errors)
        wan = _iface(s.get("wan"), where + ".wan", errors, need_gateway=True)
        backup = None
        if s.get("backup_wan"):
            backup = _iface(s["backup_wan"], where + ".backup_wan", errors, need_gateway=True)
            _key(s.get("backup_public_key"), where + ".backup_public_key", errors)
        _key(s.get("public_key"), where + ".public_key", errors)
        sites.append({"name": name, "id": sid, "lan": lan, "lan_if": (s.get("lan") or {}).get("interface"),
                      "wan": wan, "wan_raw": s.get("wan") or {}, "backup": backup,
                      "backup_raw": s.get("backup_wan") or {},
                      "public_key": s.get("public_key"), "backup_public_key": s.get("backup_public_key")})

    nets = [(s["name"], s["lan"].network) for s in sites if s["lan"]]
    for a in range(len(nets)):
        for b in range(a + 1, len(nets)):
            if nets[a][1].overlaps(nets[b][1]):
                errors.append("LAN subnets overlap: %s %s and %s %s"
                              % (nets[a][0], nets[a][1], nets[b][0], nets[b][1]))
    for kind in ("primary", "backup"):
        net = tunnel.get(kind + "_subnet")
        if net is not None:
            for s in sites:
                if isinstance(s["id"], int) and s["id"] >= net.num_addresses - 1:
                    errors.append("site %s: id %s does not fit in %s" % (s["name"], s["id"], net))
            for name, lan in nets:
                if lan.overlaps(net):
                    errors.append("tunnel.%s_subnet overlaps LAN of %s" % (kind, name))

    if errors:
        raise ConfigError("\n".join(errors))
    return {"tunnel": tunnel, "management_sources": mgmt, "sites": sites}
