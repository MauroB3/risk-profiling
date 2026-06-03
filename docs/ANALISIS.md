# Documento de análisis — User Risk Profiling

Análisis del sistema de scoring de riesgo por usuario: hallazgos, decisiones de
modelado, limitaciones y monitoreo en producción. Acompaña al código en
`risk_profiling/` y a las notebooks en `notebooks/`.

---

## 1. Hallazgos principales

El riesgo está **muy concentrado**: de 500 usuarios, 14 (2.8%) caen en `HIGH` o
`VERY_HIGH` y 468 (93.6%) en `LOW`. Más de la mitad (261) no dispara ninguna
señal. Las anomalías no están en la integridad de los datos —que es sólida— sino
en el **comportamiento**.

| Categoría | Usuarios |
|---|---|
| `VERY_HIGH` | 5 |
| `HIGH` | 9 |
| `MEDIUM` | 18 |
| `LOW` | 468 |

### Los usuarios más riesgosos, por arquetipo

Los catorce casos elevados se agrupan en cinco patrones de comportamiento:

| Arquetipo | Usuarios | Señal |
|---|---|---|
| **Acceso sin permiso** | USR0080 (84), USR0060 (27), USR0040 (25), USR0041 (25) | accesos a recursos no asignados, varios sobre `api_internal` y `payment_portal` |
| **Permisos vencidos** | USR0050 (45), USR0051 (48) | uso sostenido de permisos ya expirados |
| **Cuenta inactiva activa** | USR0012, USR0010, USR0011 | cuentas `Inactive` que registran actividad reciente |
| **Horario inusual** | USR0030 (100%), USR0012 (56%), USR0010 (50%), USR0011 (48%), USR0050 (47%), USR0070 (41%), USR0051 (33%) | accesos fuera del horario laboral (antes de 7h o después de 20h) |
| **Volumen anómalo** | USR0070 (z≈49), USR0020 (z≈40), USR0021 (z≈40) | actividad muy por encima de sus pares de mismo departamento y rol |

Un mismo usuario puede figurar en más de un arquetipo cuando dispara varias
señales: son precisamente los casos multi-señal de mayor score (por ejemplo, las
cuentas inactivas USR0010/11/12 también aparecen por horario inusual).

### Lectura de los resultados

**Los peores son multi-señal.** Los cinco `VERY_HIGH` combinan acceso sin
permiso con volumen elevado (USR0040/60/80) o permisos vencidos con horario
inusual (USR0050). La combinación de señales —no el extremo de una sola— es lo
que separa la cima.

**El volumen extremo por sí solo no domina.** USR0020 y USR0021, con ~396
accesos (≈10× la mediana), quedan en `HIGH`, por debajo de los multi-señal. Es
una decisión deliberada: un volumen alto admite explicación benigna (un
power-user real), mientras que acceder a recursos no asignados no la tiene. El
modelo prioriza la evidencia inequívoca.

**Un falso positivo de borde.** USR0443 (`HIGH`, score 20) aparece solo por
volumen (z≈5.2) sin ninguna otra señal, y no es uno de los casos anómalos
esperados. Ilustra un límite del modelo: una única señal moderada puede empujar
a `HIGH`. Se discute en la sección de limitaciones.

---

## 2. Decisiones de modelado

El score es una **suma ponderada de cinco señales de comportamiento** (H1–H5),
normalizadas a [0,1]. Se eligió una heurística por sobre un modelo de ML como
motor principal: es **explicable** (cada punto del score se atribuye a una señal,
lo que produce las `top_signals` directamente) y las señales ya estaban
validadas en el EDA. Un Isolation Forest cumple el rol de validación, no de
motor.

| Decisión | Por qué | Trade-off |
|---|---|---|
| **Heurística** como motor (no clustering ni ML) | explicabilidad y señales ya validadas; el `top_signals` sale del propio score | no descubre patrones nuevos fuera de las 5 señales |
| **5 señales** (H1–H5); se descartan H6 y H7 | en el EDA la criticidad por acción era uniforme (H6) y los externos resultaron más limpios (H7) | se asume que no hay señal en esos cruces |
| **z-score robusto** (mediana/MAD) para volumen vs. peer group | mide magnitud de desvío, robusto a los propios outliers; compara contra pares de mismo `department`+`role` | en grupos chicos cae a estadísticos globales, menos específicos |
| **Saturación** de cada señal (caps) | pasado un umbral "más no es más riesgoso"; evita que un único outlier domine | pierde orden dentro de una misma señal en el extremo |
| **Pesos por severidad** (suman 1) | sin etiquetas no se pueden aprender; se ordenan por cuán inequívoca es cada señal | elección subjetiva (mitigada con análisis de sensibilidad) |
| **Umbrales absolutos** para las categorías | 52% de los usuarios tienen score 0: un corte por percentiles caería dentro de esa masa | los cortes son fijos y deben recalibrarse si cambia la población |

**Validación.** El Isolation Forest se entrena sobre las mismas features pero sin
los pesos ni los cortes de la heurística. Su ranking coincide en el **top-14
(14/14)** y correlaciona con el score (**Spearman ρ = 0.96**): dos métodos con
supuestos distintos llegan al mismo orden, lo que indica que el resultado no es
un artefacto de la calibración manual.

---

## 3. Limitaciones

El modelo ve solo lo que está en los tres CSV, y de forma estática. Sus límites
principales y los datos que los mitigarían:

| Limitación | Dato/contexto que la mitigaría |
|---|---|
| **Sin fecha de baja**: no se puede confirmar si el acceso de una cuenta `Inactive` fue posterior a la desactivación (señal H2 ambigua) | historial de cambios de `status` con timestamp |
| **Sin incidentes etiquetados**: los pesos y umbrales se fijan a juicio, sin poder medir precisión/recall; la validación por IDs anómalos es propia del dataset y no generaliza | casos históricos etiquetados (incidente / no incidente) |
| **Snapshot estático**: agrega todo el período en un número y no detecta cambios de patrón en el tiempo (una cuenta que se vuelve anómala) | scoring por ventana temporal / series de tiempo |
| **Sin contexto de sesión**: no hay IP, geolocalización ni dispositivo, y el off-hours asume un único horario laboral para todos | metadatos de acceso (IP/geo/device) y huso o turno por usuario |
| **Sin volumen de datos**: cuenta accesos, no cuánta información se mueve; un `EXPORT` masivo pesa igual que uno chico | bytes o registros por acceso |
| **Falsos positivos por señal única**: un volumen alto sin más contexto puede ser un power-user legítimo (caso USR0443) | señales adicionales correlacionadas que confirmen la anomalía |

---

## 4. Monitoreo en producción

Hoy el score se computa al iniciar la API y se sirve desde memoria. En producción
hay que vigilar que **entren datos sanos**, que **el modelo siga siendo válido**
y que **el servicio responda** —y cerrar el bucle de feedback que hoy falta.

| Qué se monitorea | Alerta |
|---|---|
| **Frescura y calidad de ingesta**: antigüedad del último log, volumen por corrida, nulos e IDs que no cruzan | sin datos nuevos, salto de volumen (±50%) o caída de calidad vs. baseline del EDA |
| **Drift de distribución**: hoy 93.6% `LOW`, 2.8% `HIGH`+ | `HIGH+` sostenido > 5% → incidente real o umbrales descalibrados (recordar que son absolutos) |
| **Tasa de disparo por señal** (H1–H5) y estadísticos del peer group | fracción anómala de disparos, o corrimiento de mediana/MAD que descoloca el z-score |
| **Concordancia heurística ↔ Isolation Forest** (hoy ρ = 0.96) | caída de la correlación → los métodos dejaron de coincidir |
| **Servicio**: staleness del cómputo, latencia/errores de los endpoints | cómputo más viejo que el SLA, p99 alto o 5xx > 1% |
| **Transiciones de riesgo**: usuario que entra a `HIGH`/`VERY_HIGH` o pasa a multi-señal | alerta de negocio prioritaria (compensa el carácter de *snapshot*) |

El paso que más valor agrega es capturar la **disposición del analista**
(verdadero/falso positivo) sobre cada caso escalado: acumular esas etiquetas es
lo que permite medir precisión/recall y ajustar pesos con evidencia, cerrando la
principal limitación de la sección 3.
