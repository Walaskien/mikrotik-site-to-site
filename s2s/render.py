"""Render one RouterOS 7 script per site from a validated config."""
import os

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _host(net, n):
    return str(net.network_address + n)


def _with_prefix(net, n):
    return "%s/%d" % (_host(net, n), net.prefixlen)


def _peer_view(local, peer, tunnel):
    """What `local` needs to know about `peer`."""
    view = {
        "name": peer["name"],
        "lan": str(peer["lan"].network),
        "primary": {
            "key": peer["public_key"],
            "endpoint": str(peer["wan"].ip),
            "tunnel_ip": _host(tunnel["primary_subnet"], peer["id"]),
        },
        "backup": None,
    }
    if local["backup"] and peer["backup"]:
        view["backup"] = {
            "key": peer["backup_public_key"],
            "endpoint": str(peer["backup"].ip),
            "tunnel_ip": _host(tunnel["backup_subnet"], peer["id"]),
        }
    return view


def build_context(cfg, site):
    t = cfg["tunnel"]
    peers = [_peer_view(site, p, t) for p in cfg["sites"] if p is not site]
    return {
        "site": site,
        "t": t,
        "mgmt": cfg["management_sources"],
        "peers": peers,
        "has_backup": site["backup"] is not None,
        "primary_ip": _with_prefix(t["primary_subnet"], site["id"]),
        "backup_ip": _with_prefix(t["backup_subnet"], site["id"]),
        "peer_lans": [p["lan"] for p in peers],
    }


def render_all(cfg):
    """Return {filename: text}. Output depends only on the input (no timestamps)."""
    env = Environment(
        loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
        undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    tpl = env.get_template("router.rsc.j2")
    return {"%s.rsc" % s["name"]: tpl.render(**build_context(cfg, s)) for s in cfg["sites"]}
