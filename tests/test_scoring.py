"""Tests del modelo de scoring (Parte 2).

Usan los CSV reales de `data/` como fixture: además de chequear invariantes,
sirven de regresión sobre las anomalías conocidas del dataset.
"""

from pathlib import Path

import numpy as np
import pytest

from risk_profiling.scoring import ETIQUETAS, compute_risk_scores

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def df():
    return compute_risk_scores(DATA)


def test_una_fila_por_usuario(df):
    assert len(df) == 500
    assert df.user_id.is_unique
    assert {"user_id", "score", "category", "top_signals"} <= set(df.columns)


def test_rango_de_score(df):
    assert df.score.between(0, 100).all()


def test_categorias_validas(df):
    assert set(df.category.dropna().unique()) <= set(ETIQUETAS)


def test_vol_z_finito(df):
    # el fallback de _peer_z (grupos chicos / MAD=0) no debe dejar NaN ni inf
    assert np.isfinite(df.vol_z).all()


def test_anomalias_conocidas_very_high(df):
    cat = df.set_index("user_id").category
    for u in ["USR0040", "USR0060", "USR0080"]:
        assert cat[u] == "VERY_HIGH"


def test_cuentas_inactivas_flaggeadas(df):
    inact = df.set_index("user_id").inactiva_activa
    for u in ["USR0010", "USR0011", "USR0012"]:
        assert inact[u] == 1


def test_usuario_limpio(df):
    # un usuario sin ninguna señal: score 0, LOW y sin top_signals
    fila = df[df.score == 0].iloc[0]
    assert fila.category == "LOW"
    assert fila.top_signals == []
