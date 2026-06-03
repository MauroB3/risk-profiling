"""Modelo de scoring de riesgo por usuario (Parte 2).

Calcula un risk score 0-100 y una categoría (LOW/MEDIUM/HIGH/VERY_HIGH) por
usuario a partir de cinco señales de comportamiento confirmadas en el EDA
(H1-H5), junto con las señales que explican cada score.

La lógica replica la notebook `notebooks/2_scoring.ipynb`. `compute_risk_scores`
es el punto de entrada que reutiliza la API (Parte 3).
"""

from pathlib import Path

import numpy as np
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


def load_data(data_dir="data"):
    """Carga los tres CSV de entrada desde `data_dir`."""
    data = Path(data_dir)
    users = pd.read_csv(data / "user_inventory.csv",       parse_dates=["created_at"])
    perms = pd.read_csv(data / "permission_inventory.csv", parse_dates=["assigned_at", "expires_at"])
    logs  = pd.read_csv(data / "access_logs.csv",          parse_dates=["timestamp"])
    return users, perms, logs


def build_features(users, perms, logs):
    """Construye la tabla de features (una fila por usuario) con las 5 señales."""
    logs = logs.copy()
    perm_pairs = set(zip(perms.user_id, perms.resource_id))
    logs["sin_permiso"] = [(u, r) not in perm_pairs for u, r in zip(logs.user_id, logs.resource_id)]
    hora = logs.timestamp.dt.hour
    logs["off_hours"] = (hora < 7) | (hora > 20)

    feat = logs.groupby("user_id").agg(
        volumen       = ("timestamp",   "size"),
        n_sin_permiso = ("sin_permiso", "sum"),
        pct_off_hours = ("off_hours",   "mean"),
    ).reset_index()

    # H5 — accesos con permiso ya expirado
    venc = perms.dropna(subset=["expires_at"])[["user_id", "resource_id", "expires_at"]]
    acc_exp = logs.merge(venc, on=["user_id", "resource_id"]).query("timestamp > expires_at")
    feat["n_expirados"] = feat.user_id.map(acc_exp.user_id.value_counts()).fillna(0).astype(int)

    # H2 — cuenta inactiva con actividad
    inactivas = set(users.loc[users.status == "Inactive", "user_id"])
    feat["inactiva_activa"] = feat.user_id.isin(inactivas).astype(int)

    # H3 — volumen relativo al peer group (department + role)
    feat = feat.merge(users[["user_id", "department", "role"]], on="user_id")
    feat["vol_z"] = _volumen_relativo(feat)
    return feat


def _robust_z(x, med, mad, mad_fallback):
    """z robusto = (x - mediana) / (1.4826 * MAD), recortado en 0 (solo alto)."""
    escala = 1.4826 * np.where(mad > 0, mad, mad_fallback)
    return ((x - med) / escala).clip(lower=0)


def _volumen_relativo(feat):
    """z-score robusto del volumen dentro del peer group; fallback global si el grupo es chico."""
    peer_group = feat.department + " / " + feat.role
    g = feat.groupby(peer_group).volumen
    med   = g.transform("median")
    mad_g = g.transform(lambda s: (s - s.median()).abs().median())
    tam   = g.transform("size")
    med_pob = feat.volumen.median()
    mad_pob = (feat.volumen - med_pob).abs().median()

    z_grupo  = _robust_z(feat.volumen, med,     mad_g,   mad_pob)
    z_global = _robust_z(feat.volumen, med_pob, mad_pob, mad_pob)
    return z_grupo.where(tam >= MIN_PEERS, z_global)


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
    feat["category"] = pd.cut(
        feat.score, bins=CORTES, labels=ETIQUETAS, right=False, include_lowest=True,
    )
    feat["top_signals"] = [_top_signals(contrib.loc[i], feat.loc[i]) for i in feat.index]
    return feat


def _top_signals(aportes, fila, n=3):
    """Las n señales que más aportaron al score, como texto legible."""
    señales = aportes[aportes > 0].sort_values(ascending=False).index[:n]
    return [TEXTOS[s](fila) for s in señales]


def compute_risk_scores(data_dir="data"):
    """Punto de entrada: de los CSV en `data_dir` a la tabla scoreada por usuario."""
    users, perms, logs = load_data(data_dir)
    feat = build_features(users, perms, logs)
    return score_users(feat)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Scoring de riesgo por usuario (Parte 2).")
    parser.add_argument("--data", default="data", help="carpeta con los CSV de entrada")
    parser.add_argument("--out",  default="outputs/risk_scores.csv", help="archivo CSV de salida")
    args = parser.parse_args()

    df = compute_risk_scores(args.data).sort_values("score", ascending=False)

    salida = df[["user_id", "score", "category", "top_signals"]].copy()
    salida["top_signals"] = salida.top_signals.apply(lambda xs: " | ".join(xs))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    salida.to_csv(out, index=False)

    print(f"{len(df)} usuarios scoreados -> {out}")
    print(df.category.value_counts().reindex(ETIQUETAS[::-1]).to_string())


if __name__ == "__main__":
    main()
