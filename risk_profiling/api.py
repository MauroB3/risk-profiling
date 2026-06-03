"""API REST de risk profiling (Parte 3).

Los scores se computan una sola vez al iniciar y se sirven desde memoria: el
volumen de datos es chico y el módulo de scoring es la única fuente de verdad,
por lo que no se persiste ni se depende de ningún CSV pre-generado.

Correr localmente:

    uvicorn risk_profiling.api:app --reload

Docs interactivas en http://localhost:8000/docs
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from risk_profiling.scoring import ETIQUETAS, compute_risk_scores

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Scores computados al importar el módulo, ordenados por riesgo.
_scores = compute_risk_scores(DATA_DIR).sort_values("score", ascending=False)
_by_user = _scores.set_index("user_id")

app = FastAPI(title="Risk Profiling API", version="1.0")


class RiskResponse(BaseModel):
    user_id: str
    score: float
    category: str
    top_signals: list[str]


def _to_response(user_id, row) -> RiskResponse:
    return RiskResponse(
        user_id=user_id,
        score=float(row.score),
        category=str(row.category),
        top_signals=list(row.top_signals),
    )


@app.get("/users/{user_id}/risk", response_model=RiskResponse)
def get_user_risk(user_id: str):
    """Score, categoría y señales principales de un usuario."""
    if user_id not in _by_user.index:
        raise HTTPException(status_code=404, detail=f"Usuario {user_id} no encontrado")
    return _to_response(user_id, _by_user.loc[user_id])


@app.get("/users", response_model=list[RiskResponse])
def list_users(
    category: str | None = Query(None, description="Filtra por categoría de riesgo"),
    limit: int = Query(10, ge=1, le=500, description="Máximo de usuarios a devolver"),
):
    """Usuarios ordenados por score descendente, opcionalmente filtrados por categoría."""
    df = _scores
    if category is not None:
        category = category.upper()
        if category not in ETIQUETAS:
            raise HTTPException(status_code=422, detail=f"category inválida; usar una de {ETIQUETAS}")
        df = df[df.category == category]
    return [_to_response(r.user_id, r) for r in df.head(limit).itertuples()]
