import copy
import os

import pytest
import yaml

from s2s.cli import main
from s2s.config import ConfigError, validate
from s2s.render import render_all

HERE = os.path.dirname(__file__)
EXAMPLE = os.path.join(HERE, "..", "examples", "three-sites.yml")
GOLDEN = os.path.join(HERE, "golden")


def example():
    with open(EXAMPLE) as fh:
        return yaml.safe_load(fh)


def bad(mutate):
    raw = example()
    mutate(raw)
    with pytest.raises(ConfigError) as exc:
        validate(raw)
    return str(exc.value)


@pytest.mark.parametrize("name", ["hq", "branch1", "branch2"])
def test_output_matches_golden(name):
    out = render_all(validate(example()))["%s.rsc" % name]
    path = os.path.join(GOLDEN, "%s.rsc" % name)
    if os.environ.get("UPDATE_GOLDEN"):
        with open(path, "w") as fh:
            fh.write(out)
    with open(path) as fh:
        assert out == fh.read()


def test_output_is_deterministic():
    cfg = validate(example())
    assert render_all(cfg) == render_all(validate(copy.deepcopy(example())))


def test_site_without_backup_gets_no_backup_tunnel():
    files = render_all(validate(example()))
    assert "wg-backup" not in files["branch2.rsc"]
    assert "wg-backup" in files["hq.rsc"]
    # hq has a backup link, but branch2 does not: no backup peer towards branch2
    assert "branch2-backup" not in files["hq.rsc"]
    assert "branch1-backup" in files["hq.rsc"]


def test_every_site_routes_to_every_other_lan():
    files = render_all(validate(example()))
    assert "dst-address=10.20.0.0/24 gateway=10.255.1.2 distance=1" in files["hq.rsc"]
    assert "dst-address=10.10.0.0/24 gateway=10.255.1.1 distance=1" in files["branch2.rsc"]
    assert "10.30.0.0/24" not in files["branch2.rsc"].split("# --- address lists")[1]


def test_no_private_keys_in_output():
    for text in render_all(validate(example())).values():
        assert "private-key" not in text


def test_rejects_overlapping_lans():
    msg = bad(lambda r: r["sites"][1]["lan"].update(address="10.10.0.254/24"))
    assert "overlap" in msg


def test_rejects_duplicate_name_and_id():
    def mutate(r):
        r["sites"][1]["name"] = "hq"
        r["sites"][1]["id"] = 1
    msg = bad(mutate)
    assert "duplicate name" in msg and "duplicate id" in msg


def test_rejects_gateway_outside_wan_subnet():
    msg = bad(lambda r: r["sites"][0]["wan"].update(gateway="192.0.2.1"))
    assert "outside" in msg


def test_rejects_bad_key_and_bad_address():
    def mutate(r):
        r["sites"][0]["public_key"] = "not-a-key"
        r["sites"][2]["lan"]["address"] = "10.30.0.999/24"
    msg = bad(mutate)
    assert "public key" in msg and "invalid address" in msg


def test_rejects_equal_ports_and_single_site():
    assert "must differ" in bad(lambda r: r["tunnel"].update(backup_port=13231))
    assert "at least two" in bad(lambda r: r.update(sites=r["sites"][:1]))


def test_backup_wan_requires_backup_key():
    def mutate(r):
        del r["sites"][0]["backup_public_key"]
    assert "backup_public_key" in bad(mutate)


def test_cli_validate_and_generate(tmp_path, capsys):
    assert main(["validate", EXAMPLE]) == 0
    assert main(["generate", EXAMPLE, "-o", str(tmp_path)]) == 0
    assert sorted(os.listdir(tmp_path)) == ["branch1.rsc", "branch2.rsc", "hq.rsc"]


def test_cli_reports_invalid_config(tmp_path, capsys):
    p = tmp_path / "bad.yml"
    p.write_text("sites: []\n")
    assert main(["validate", str(p)]) == 1
    assert "Invalid config" in capsys.readouterr().err
