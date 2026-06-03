"""Modelo de scoring de riesgo por usuario (Parte 2).

Calcula un risk score 0-100 y una categoría (LOW/MEDIUM/HIGH/VERY_HIGH) por
usuario a partir de cinco señales de comportamiento confirmadas en el EDA
(H1-H5), con las señales que explican cada score. Replica la lógica de
`notebooks/2_scoring.ipynb`. `compute_risk_scores` es el punto de entrada que
reutiliza la API (Parte 3).
"""

from pathlib import Path

import pandas as pd

# --- Configuración del modelo (editable según política de seguridad) ---

# Pesos por señal (suman 1); reflejan severidad de seguridad.
PESOS = {
    "sin_permiso":     0.30,  # acceso a recursos no asignados: la más inequívoca
    "volumen":         0.20,  # actividad muy por encima de los pares
    "off_hours":       0.20,  # accesos fuera de horario laboral
    "inactiva_activa": 0.15,  # cuenta inactiva con actividad (peso medio: ambigüedad)
    "expirados":       0.15,  # uso de permisos vencidos
}

# Caps de saturación: más allá de esto la señal "ya es máxima".
CAP_Z, CAP_PERM, CAP_EXP = 3.5, 10, 5

MIN_PEERS = 5  # debajo de esto el peer group es muy chico para una dispersión confiable

# Cortes de categoría (puntos de score) y etiquetas, de menor a mayor riesgo.
CORTES = [0, 10, 20, 30, 100]
ETIQUETAS = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]

# Texto legible por señal, usando los valores reales del usuario.
TEXTOS = {
    "sin_permiso":     lambda r: f"Accede a {int(r.n_sin_permiso)} recursos sin permiso asignado",
    "volumen":         lambda r: f"Volumen {r.vol_z:.0f}σ por encima de su peer group",
    "off_hours":       lambda r: f"{r.pct_off_hours:.0%} de accesos fuera de horario",
    "inactiva_activa": lambda r: "Cuenta inactiva con actividad reciente",
    "expirados":       lambda r: f"{int(r.n_expirados)} accesos con permiso vencido",
}


def compute_risk_scores(data_dir="data"):
    """De los CSV en `data_dir` a la tabla scoreada por usuario."""
    users, perms, logs = load_data(data_dir)
    return score_users(build_features(users, perms, logs))


def load_data(data_dir="data"):
    """Carga los tres CSV de entrada desde `data_dir`."""
    d = Path(data_dir)
    users = pd.read_csv(d / "user_inventory.csv",       parse_dates=["created_at"])
    perms = pd.read_csv(d / "permission_inventory.csv", parse_dates=["assigned_at", "expires_at"])
    logs  = pd.read_csv(d / "access_logs.csv",          parse_dates=["timestamp"])
    return users, perms, logs


def build_features(users, perms, logs):
    """Tabla de features (una fila por usuario) con las 5 señales H1-H5."""
    logs = logs.copy()
    perm_pairs = set(zip(perms.user_id, perms.resource_id))
    logs["sin_permiso"] = [(u, r) not in perm_pairs for u, r in zip(logs.user_id, logs.resource_id)]
    logs["off_hours"] = (logs.timestamp.dt.hour < 7) | (logs.timestamp.dt.hour > 20)

    feat = logs.groupby("user_id").agg(
        volumen       = ("timestamp",   "size"),   # H3
        n_sin_permiso = ("sin_permiso", "sum"),    # H1
        pct_off_hours = ("off_hours",   "mean"),   # H4
    ).reset_index()

    # H5 — accesos con un permiso ya expirado
    venc = perms.dropna(subset=["expires_at"])[["user_id", "resource_id", "expires_at"]]
    usados_vencidos = logs.merge(venc, on=["user_id", "resource_id"]).query("timestamp > expires_at")
    feat["n_expirados"] = feat.user_id.map(usados_vencidos.user_id.value_counts()).fillna(0).astype(int)

    # H2 — cuenta inactiva con actividad
    inactivas = set(users.loc[users.status == "Inactive", "user_id"])
    feat["inactiva_activa"] = feat.user_id.isin(inactivas).astype(int)

    # H3 — volumen relativo al peer group (department + role)
    feat = feat.merge(users[["user_id", "department", "role"]], on="user_id")
    feat["vol_z"] = _peer_z(feat)
    return feat


def _peer_z(feat):
    """z-score robusto del volumen vs. el peer group.

    z = (volumen - mediana) / (1.4826 * MAD), recortado en 0 (solo volumen alto).
    El MAD es robusto a outliers; el 1.4826 lo lleva a escala de sigma. En grupos
    chicos (< MIN_PEERS) o con MAD = 0 se usa la mediana/MAD de toda la población.
    """
    grp = feat.groupby(feat.department + " / " + feat.role).volumen
    med = grp.transform("median")
    mad = grp.transform(lambda s: (s - s.median()).abs().median())
    chico = grp.transform("size") < MIN_PEERS

    med_pob = feat.volumen.median()
    mad_pob = (feat.volumen - med_pob).abs().median()
    med = med.where(~chico, med_pob)
    mad = mad.where(~chico & (mad > 0), mad_pob)

    return ((feat.volumen - med) / (1.4826 * mad)).clip(lower=0)


def score_users(feat):
    """Agrega score, category y top_signals a la tabla de features."""
    sev = pd.DataFrame({
        "sin_permiso":     (feat.n_sin_permiso / CAP_PERM).clip(upper=1),
        "volumen":         (feat.vol_z         / CAP_Z   ).clip(upper=1),
        "off_hours":        feat.pct_off_hours.clip(upper=1),
        "inactiva_activa":  feat.inactiva_activa,
        "expirados":       (feat.n_expirados   / CAP_EXP ).clip(upper=1),
    })
    contrib = sev * pd.Series(PESOS)  # aporte de cada señal al score

    feat = feat.copy()
    feat["score"] = (contrib.sum(axis=1) * 100).round(1)
    feat["category"] = pd.cut(feat.score, bins=CORTES, labels=ETIQUETAS, right=False, include_lowest=True)
    feat["top_signals"] = [_top_signals(contrib.loc[i], feat.loc[i]) for i in feat.index]
    return feat


def _top_signals(aportes, fila, n=3):
    """Las n señales que más aportaron al score, como texto legible."""
    señales = aportes[aportes > 0].sort_values(ascending=False).index[:n]
    return [TEXTOS[s](fila) for s in señales]


def main():
    """CLI: scorea los CSV de `data/` y escribe `outputs/risk_scores.csv`."""
    df = compute_risk_scores().sort_values("score", ascending=False)

    salida = df[["user_id", "score", "category", "top_signals"]].copy()
    salida["top_signals"] = salida.top_signals.str.join(" | ")

    out = Path("outputs/risk_scores.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    salida.to_csv(out, index=False)

    print(f"{len(df)} usuarios scoreados -> {out}")
    print(df.category.value_counts().reindex(ETIQUETAS[::-1]).to_string())


if __name__ == "__main__":
    main()
