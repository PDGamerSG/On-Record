from __future__ import annotations

from wsw_brain.__main__ import main


def test_main_runs_api_app_with_uvicorn(monkeypatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("wsw_brain.__main__.uvicorn.run", fake_run)

    main([])

    assert calls == [
        (
            ("wsw_brain.app:app",),
            {"host": "127.0.0.1", "port": 8000},
        )
    ]


def test_main_accepts_server_options(monkeypatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("wsw_brain.__main__.uvicorn.run", fake_run)

    main(["--host", "0.0.0.0", "--port", "9100", "--reload"])

    assert calls == [
        (
            ("wsw_brain.app:app",),
            {"host": "0.0.0.0", "port": 9100, "reload": True},
        )
    ]
