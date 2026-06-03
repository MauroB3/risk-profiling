# User Risk Profiling Challenge

Sistema de detección de comportamientos anómalos y scoring de riesgo por usuario,
a partir de logs de accesos y el inventario de permisos.

## Setup

```bash
pip install -r requirements.txt
```

## Parte 1 — EDA

Análisis exploratorio, calidad de datos e hipótesis de anomalías:

```bash
jupyter lab notebooks/1_eda.ipynb
```

## Parte 2 — Scoring de riesgo

Modelo de scoring por usuario (heurística sobre 5 señales de comportamiento,
validada con Isolation Forest). La narrativa está en la notebook:

```bash
jupyter lab notebooks/2_scoring.ipynb
```

La lógica está empaquetada en `risk_profiling/`. Para generar los scores sobre
los CSV de `data/` y escribir `outputs/risk_scores.csv`:

```bash
python -m risk_profiling
```

Reutilizable como librería (lo consume la API de la Parte 3):

```python
from risk_profiling import compute_risk_scores

df = compute_risk_scores("data")  # user_id, score, category, top_signals, ...
```

## Parte 3 — API REST

La API computa los scores en memoria al iniciar (los datos son chicos) y los
sirve desde ahí; no depende de ningún CSV pre-generado.

```bash
uvicorn risk_profiling.api:app --reload
```

Endpoints (docs interactivas en `http://localhost:8000/docs`):

```
GET /users/{user_id}/risk        # score, categoría y señales de un usuario
GET /users?category=HIGH&limit=10  # usuarios por categoría, ordenados por score desc
```

## Parte 4 — Documento de análisis

Hallazgos, decisiones de modelado, limitaciones y monitoreo en producción:
[`docs/ANALISIS.md`](docs/ANALISIS.md).

## Bonus — Dashboard

Reporte visual (distribución por categoría, top 10 con señales y comportamiento
vs. peer group). Se puede abrir directamente [`docs/dashboard.html`](docs/dashboard.html),
o regenerarlo —se escribe ahí mismo y se abre en el navegador—:

```bash
python -m risk_profiling.dashboard
```

## Tests

```bash
pytest
```

## Estructura

```
risk-profiling/
├── data/                  # CSVs de entrada
├── docs/                  # Challenge, análisis (Parte 4) y dashboard
│   ├── ANALISIS.md        # Parte 4 — documento de análisis
│   └── dashboard.html     # Bonus — reporte visual generado
├── notebooks/
│   ├── 1_eda.ipynb        # Parte 1 — EDA
│   └── 2_scoring.ipynb    # Parte 2 — scoring (narrativa)
├── risk_profiling/        # Paquete
│   ├── scoring.py         # Modelo de scoring (Parte 2)
│   ├── api.py             # API REST (Parte 3)
│   ├── dashboard.py       # Bonus — dashboard (python -m risk_profiling.dashboard)
│   └── __main__.py        # CLI: python -m risk_profiling
├── tests/                 # Tests de scoring y API
├── outputs/               # Resultados generados (no versionado)
├── requirements.txt
└── README.md
```
