"""Komut satırı araçları."""
from app.cli import main


def test_cli_commands(capsys):
    assert main(["init-db"]) == 0
    assert main(["run-job", "olmayan"]) == 2
    assert main(["run-job", "uptake"]) == 0
    assert main(["create-admin", "ikinci@otelradar.local", "kisa"]) == 2
    assert main(["create-admin", "ikinci@otelradar.local", "Parola123", "İkinci Yönetici"]) == 0
    assert main(["create-admin", "ikinci@otelradar.local", "Parola123"]) == 2
    assert main(["seed"]) == 0  # veri varsa atlanır
    out = capsys.readouterr().out
    assert "Yönetici oluşturuldu" in out and "zaten" in out
