"""Dashboard visual del scoring de riesgo (bonus track).

Genera un HTML estático autocontenido a partir del módulo de scoring —sin lógica
nueva, solo presenta la tabla que ya produce `compute_risk_scores`— con las tres
vistas que pide el bonus: distribución por categoría, top 10 de usuarios con sus
señales y comportamiento vs. peer group.

Correr:

    python -m risk_profiling.dashboard

Escribe `docs/dashboard.html` (versionado como entrega) y lo abre en el navegador.
"""

import contextlib
import os
import webbrowser
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go

from risk_profiling.scoring import ETIQUETAS, compute_risk_scores

# Color por categoría, de menor a mayor riesgo.
COLORES = dict(zip(ETIQUETAS, ["#2ecc71", "#f1c40f", "#e67e22", "#e74c3c"]))


def build_dashboard(data_dir="data"):
    """Construye las tres figuras y las devuelve como fragmentos HTML."""
    df = compute_risk_scores(data_dir).sort_values("score", ascending=False)

    # 1. Distribución de usuarios por categoría de riesgo.
    dist = (df.category.value_counts().reindex(ETIQUETAS).fillna(0)
            .rename_axis("Categoría").reset_index(name="Usuarios"))
    fig_dist = px.bar(
        dist, x="Categoría", y="Usuarios", color="Categoría", color_discrete_map=COLORES,
        text="Usuarios", title="Usuarios por categoría de riesgo",
    ).update_layout(showlegend=False).update_traces(
        hovertemplate="%{x}: %{y} usuarios<extra></extra>")

    # 2. Top 10 usuarios más críticos con sus señales.
    top = df.head(10)
    fig_top = go.Figure(go.Table(
        header=dict(values=["Usuario", "Score", "Categoría", "Señales principales"],
                    fill_color="#34495e", font_color="white", align="left"),
        cells=dict(values=[top.user_id, top.score, top.category,
                           top.top_signals.str.join(" · ")], align="left"),
    )).update_layout(title="Top 10 usuarios más críticos")

    # 3. Comportamiento vs. peer group: volumen y su desvío (σ) sobre los pares.
    fig_peer = px.scatter(
        df, x="volumen", y="vol_z", color="category", color_discrete_map=COLORES,
        hover_name="user_id", category_orders={"category": ETIQUETAS},
        labels={"volumen": "Accesos", "vol_z": "Desvío vs. peer group (σ)", "category": "Categoría"},
        title="Volumen vs. peer group (department + role)",
    )

    # Estilo común: alto acotado y márgenes ajustados para que no queden gigantes.
    figs = [fig_dist, fig_top, fig_peer]
    for fig in figs:
        fig.update_layout(template="plotly_white", height=340, margin=dict(t=50, b=40, l=50, r=20))
    return figs


def main():
    """Genera `outputs/dashboard.html` con las tres vistas y lo abre."""
    figs = build_dashboard()

    # Contenedor centrado con ancho máximo: evita que los gráficos se estiren en pantallas grandes.
    partes = ["<div style='max-width:900px;margin:0 auto;font-family:sans-serif'>",
              "<h1>Risk Profiling — Dashboard</h1>"]
    for i, fig in enumerate(figs):
        partes.append(fig.to_html(full_html=False, include_plotlyjs="cdn" if i == 0 else False))
    partes.append("</div>")

    out = Path("docs/dashboard.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(partes), encoding="utf-8")

    print(f"Dashboard -> {out}  (abrir en el navegador)")
    _abrir(out)


def _abrir(path):
    """Abre el HTML en el navegador, best-effort y silencioso.

    En entornos sin navegador (WSL, CI) el lanzador escribe a fd 2 directamente,
    así que lo redirigimos a nivel de descriptor para no ensuciar la salida.
    """
    saved = os.dup(2)
    with contextlib.suppress(Exception), open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 2)
        try:
            webbrowser.open(path.resolve().as_uri())
        finally:
            os.dup2(saved, 2)
            os.close(saved)


if __name__ == "__main__":
    main()
