"""Detectores de hallazgos.

Cada detector:
  - es GENÉRICO: no conoce al cliente, solo el modelo canónico (marts);
  - declara qué necesita (`requires`). Si el cliente no tiene ese dato
    (ej. no hay unidades físicas), el detector no corre y queda registrado;
  - devuelve hallazgos con los números ya calculados.

Sumar un detector = escribir una función y decorarla con @detector.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from sawy.config import ClientConfig
from sawy.insights.models import Fact, Finding
from sawy.warehouse import Warehouse

DATE_COLUMNS = {"period", "sale_date", "last_invoice_date"}


# --------------------------------------------------------------------------- #
# Contexto compartido
# --------------------------------------------------------------------------- #
@dataclass
class Context:
    wh: Warehouse
    cfg: ClientConfig
    _cache: dict[str, pd.DataFrame] = field(default_factory=dict)

    def mart(self, name: str, schema: str = "marts") -> pd.DataFrame:
        key = f"{schema}.{name}"
        if key not in self._cache:
            df = self.wh.query_df(f"select * from {key}")
            for c in DATE_COLUMNS & set(df.columns):
                df[c] = pd.to_datetime(df[c])
            for c in ("named_customers", "is_active"):
                if c in df.columns:
                    df[c] = df[c].astype(bool)
            self._cache[key] = df
        return self._cache[key].copy()

    def by_method(self, name: str, method: str | None = None) -> pd.DataFrame:
        df = self.mart(name)
        return df[df["allocation_method"] == (method or self.default_method)]

    @property
    def default_method(self) -> str:
        return self.cfg.analysis.default_allocation_method

    @property
    def methods(self) -> list[str]:
        return list(self.cfg.analysis.allocation_methods)

    @property
    def t(self):
        return self.cfg.analysis.thresholds

    @property
    def periods(self) -> list[pd.Timestamp]:
        return sorted(self.mart("mart_pnl_monthly")["period"].tolist())

    @property
    def n_months(self) -> int:
        return max(len(self.periods), 1)

    @property
    def base_unit(self) -> str:
        return self.cfg.client.base_unit

    def product_names(self) -> dict[str, str]:
        d = self.mart("dim_products", schema="core")
        return dict(zip(d["product_id"], d["product_name"], strict=True))

    def customers(self) -> pd.DataFrame:
        return self.mart("dim_customers", schema="core")

    def sensitive_concepts(self) -> list[str]:
        return [e.concept for e in self.cfg.rules.expenses if e.sensitive]

    def sensitive_labels(self) -> str:
        labels = [e.label or e.concept.lower() for e in self.cfg.rules.expenses if e.sensitive]
        return " y ".join(labels) if labels else "los gastos compartidos"


# --------------------------------------------------------------------------- #
# Registro de detectores
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Detector:
    name: str
    fn: Callable[[Context], list[Finding]]
    requires: tuple[str, ...]


REGISTRY: list[Detector] = []

# Capacidades: qué tiene que existir para que un detector tenga sentido.
CAPABILITIES: dict[str, Callable[[Context], bool]] = {
    "base_units": lambda ctx: bool(ctx.cfg.rules.base_units_per_unit),
    "named_customers": lambda ctx: any(c.named_customers for c in ctx.cfg.rules.channels),
    "credit_notes": lambda ctx: float(ctx.mart("mart_returns")["returned_quantity"].sum()) > 0,
    "multiple_methods": lambda ctx: len(ctx.methods) > 1,
    "min_3_months": lambda ctx: ctx.n_months >= 3,
}


def detector(*requires: str):
    def wrap(fn: Callable[[Context], list[Finding]]):
        REGISTRY.append(Detector(fn.__name__, fn, requires))
        return fn

    return wrap


def _channel_word(channel: str) -> str:
    return channel.lower()


# --------------------------------------------------------------------------- #
# Detectores
# --------------------------------------------------------------------------- #
@detector("named_customers")
def loss_making_customer(ctx: Context) -> list[Finding]:
    """Clientes relevantes que, después de gastos variables, hacen perder plata."""
    df = ctx.mart("mart_contribution_by_customer")
    df = df[df["named_customers"]]
    total_rev = ctx.by_method("mart_contribution_by_customer")["revenue"].sum()
    pivot = df.pivot_table(
        index="customer_id", columns="allocation_method", values="contribution", aggfunc="sum"
    )
    base = ctx.by_method("mart_contribution_by_customer").set_index("customer_id")
    cust = ctx.customers().set_index("customer_id")

    out: list[Finding] = []
    for cid, row in pivot.iterrows():
        if cid not in base.index:
            continue
        b = base.loc[cid]
        share = b["revenue"] / total_rev if total_rev else 0
        contrib = row[ctx.default_method]
        if contrib >= 0 or share < ctx.t.min_revenue_share_customer:
            continue
        negative_everywhere = bool((row < 0).all())
        loss = -contrib
        uplift = loss / b["revenue"]  # cuánto más habría que cobrarle para quedar en cero
        facts = {
            "loss": Fact(value=loss, unit="money", label="pérdida en el período (criterio por defecto)"),
            "monthly_loss": Fact(value=loss / ctx.n_months, unit="money", label="pérdida promedio por mes"),
            "revenue_share": Fact(value=share, unit="pct", label="porcentaje de la facturación total"),
            "best_case": Fact(
                value=float(row.max()),
                unit="money",
                label="resultado con el criterio de reparto más favorable",
            ),
            "worst_case": Fact(
                value=float(row.min()),
                unit="money",
                label="resultado con el criterio de reparto más desfavorable",
            ),
            "price_increase_needed": Fact(
                value=uplift, unit="pct", label="aumento de precio neto necesario para no perder"
            ),
        }
        discount = cust.loc[cid, "discount_pct"] if cid in cust.index else None
        detail = (
            "Después de pagar el café, el flete y el packaging, cada mes se pierden "
            "[[monthly_loss]] con este cliente, que es [[revenue_share]] de la facturación."
        )
        if discount is not None and pd.notna(discount) and discount > 0:
            d = float(discount) / 100
            breakeven = 1 - (1 - d) * (1 + uplift)
            facts["discount"] = Fact(value=d, unit="pct", label="descuento actual")
            facts["breakeven_discount"] = Fact(
                value=max(breakeven, 0), unit="pct", label="descuento máximo para no perder plata"
            )
            detail += (
                " Con [[discount]] de descuento no cierra: para no perder, el descuento "
                "no debería superar [[breakeven_discount]] (o habría que cobrarle el flete)."
            )
        out.append(
            Finding(
                key=f"loss_making_customer:{cid}",
                kind="loss_making_customer",
                category="accion",
                severity="alta" if negative_everywhere else "media",
                title=f"{cust.loc[cid, 'customer_name'] if cid in cust.index else cid} te hace perder plata",
                detail=detail,
                entity_type="customer",
                entity_id=cid,
                entity_name=cust.loc[cid, "customer_name"] if cid in cust.index else cid,
                facts=facts,
                impact_monthly=loss / ctx.n_months,
                depends_on_assumption=not negative_everywhere,
            )
        )
    out.sort(key=lambda f: -f.impact_monthly)
    return out[: ctx.t.max_findings_per_kind]


@detector("multiple_methods")
def allocation_sensitive_channel(ctx: Context) -> list[Finding]:
    """Canales cuyo resultado cambia de signo según cómo se repartan los gastos."""
    df = ctx.mart("mart_contribution_by_channel")
    pivot = df.pivot_table(index="channel", columns="allocation_method", values="contribution")
    concept_txt = ctx.sensitive_labels()
    out = []
    for ch, row in pivot.iterrows():
        if (row > 0).any() and (row < 0).any():
            out.append(
                Finding(
                    key=f"allocation_sensitive_channel:{ch}",
                    kind="allocation_sensitive_channel",
                    category="accion",
                    severity="media",
                    title=f"El resultado de {ch} depende de cómo se reparta {concept_txt}",
                    detail=(
                        "Según el criterio, el canal da entre [[worst_case]] y [[best_case]] en el período. "
                        "Conviene medir una semana el costo real de cada reparto (tiempo, km, combustible) "
                        "para saber cuál criterio se parece más a la realidad."
                    ),
                    entity_type="channel",
                    entity_id=ch,
                    entity_name=ch,
                    facts={
                        "best_case": Fact(
                            value=float(row.max()),
                            unit="money",
                            label="resultado con el criterio más favorable",
                        ),
                        "worst_case": Fact(
                            value=float(row.min()),
                            unit="money",
                            label="resultado con el criterio más desfavorable",
                        ),
                    },
                    impact_monthly=float(row.max() - row.min()) / ctx.n_months / 2,
                    depends_on_assumption=True,
                )
            )
    return out


@detector("credit_notes")
def high_return_rate(ctx: Context) -> list[Finding]:
    """Productos con devoluciones altas en un canal."""
    df = ctx.mart("mart_returns")
    df = df[
        (df["return_rate"] >= ctx.t.return_rate_alert) & (df["returned_quantity"] >= ctx.t.min_returned_units)
    ]
    names = ctx.product_names()
    out = []
    for _, r in df.sort_values("returned_cost", ascending=False).iterrows():
        pname = names.get(r["product_id"], r["product_id"])
        out.append(
            Finding(
                key=f"high_return_rate:{r['channel']}:{r['product_id']}",
                kind="high_return_rate",
                category="accion",
                severity="alta" if r["return_rate"] >= 2 * ctx.t.return_rate_alert else "media",
                title=f"{pname}: demasiadas devoluciones en {_channel_word(r['channel'])}",
                detail=(
                    "Vuelve [[return_rate]] de lo que se vende (producto que se puso viejo en el cliente). "
                    "En el período se devolvieron [[returned_quantity]] unidades en [[credit_notes]] notas de crédito. "
                    "Conviene ajustar el tamaño o la frecuencia de los pedidos de esos clientes."
                ),
                entity_type="product",
                entity_id=r["product_id"],
                entity_name=pname,
                facts={
                    "return_rate": Fact(
                        value=r["return_rate"], unit="pct", label="porcentaje devuelto sobre lo vendido"
                    ),
                    "returned_quantity": Fact(
                        value=r["returned_quantity"], unit="count", label="unidades devueltas"
                    ),
                    "credit_notes": Fact(value=r["credit_notes"], unit="count", label="notas de crédito"),
                    "returned_cost_monthly": Fact(
                        value=r["returned_cost"] / ctx.n_months,
                        unit="money",
                        label="costo del café devuelto, por mes",
                    ),
                },
                impact_monthly=r["returned_cost"] / ctx.n_months,
            )
        )
    return out[: ctx.t.max_findings_per_kind]


@detector("named_customers", "min_3_months")
def customer_cooling(ctx: Context) -> list[Finding]:
    """Clientes que compran mucho menos seguido que lo habitual."""
    df = ctx.mart("mart_customer_monthly")
    periods = ctx.periods
    k = ctx.t.cooling_recent_months
    recent_p, base_p = periods[-k:], periods[:-k]
    if not base_p:
        return []
    ref_date = ctx.mart("fct_sales_lines", schema="core")["sale_date"].max()
    cust = ctx.customers().set_index("customer_id")
    out = []
    for cid, g in df.groupby("customer_id"):
        base = g[g["period"].isin(base_p)]
        recent = g[g["period"].isin(recent_p)]
        base_rate = base["invoices"].sum() / len(base_p)
        recent_rate = recent["invoices"].sum() / len(recent_p)
        if base_rate < 1 or recent_rate >= ctx.t.cooling_ratio * base_rate:
            continue
        base_rev = base["revenue"].sum() / len(base_p)
        recent_rev = recent["revenue"].sum() / len(recent_p)
        days = (ref_date - g["last_invoice_date"].max()).days
        name = cust.loc[cid, "customer_name"] if cid in cust.index else cid
        out.append(
            Finding(
                key=f"customer_cooling:{cid}",
                kind="customer_cooling",
                category="accion",
                severity="media",
                title=f"{name} está comprando mucho menos",
                detail=(
                    "Compraba [[base_orders]] veces por mes y en los últimos meses bajó a [[recent_orders]]. "
                    "Su última compra fue hace [[days_since_last]]. Vale un llamado esta semana."
                ),
                entity_type="customer",
                entity_id=cid,
                entity_name=name,
                facts={
                    "base_orders": Fact(value=base_rate, unit="rate", label="pedidos por mes, antes"),
                    "recent_orders": Fact(
                        value=recent_rate, unit="rate", label="pedidos por mes, últimos meses"
                    ),
                    "days_since_last": Fact(value=days, unit="days", label="días desde la última compra"),
                    "revenue_at_risk": Fact(
                        value=max(base_rev - recent_rev, 0),
                        unit="money",
                        label="facturación mensual que se dejó de recibir",
                    ),
                },
                impact_monthly=max(base_rev - recent_rev, 0),
            )
        )
    out.sort(key=lambda f: -f.impact_monthly)
    return out[: ctx.t.max_findings_per_kind]


@detector("min_3_months")
def strongest_channel(ctx: Context) -> list[Finding]:
    """El canal que más plata deja (y si viene creciendo)."""
    ch = ctx.by_method("mart_contribution_by_channel")
    if ch.empty or ch["contribution"].max() <= 0:
        return []
    total_rev = ch["revenue"].sum()
    best = ch.sort_values("contribution", ascending=False).iloc[0]
    monthly = ctx.by_method("mart_channel_monthly")
    monthly = monthly[monthly["channel"] == best["channel"]].sort_values("period")
    half = len(ctx.periods) // 2
    first = monthly[monthly["period"].isin(ctx.periods[:half])]["revenue"].sum()
    last = monthly[monthly["period"].isin(ctx.periods[-half:])]["revenue"].sum()
    growth = (last / first - 1) if first else 0.0
    return [
        Finding(
            key=f"strongest_channel:{best['channel']}",
            kind="strongest_channel",
            category="accion",
            severity="media",
            title=f"{best['channel']} es el canal que más plata te deja",
            detail=(
                "Después de pagar la mercadería y los gastos variables, le queda [[margin_pct]] de cada venta. "
                "Es [[revenue_share]] de la facturación y creció [[growth]] entre la primera y la segunda mitad "
                "del período. Vale la pena darle más empuje."
            ),
            entity_type="channel",
            entity_id=best["channel"],
            entity_name=best["channel"],
            facts={
                "contribution": Fact(
                    value=best["contribution"], unit="money", label="lo que dejó en el período"
                ),
                "margin_pct": Fact(
                    value=best["contribution_margin_pct"],
                    unit="pct",
                    label="margen después de gastos variables",
                ),
                "revenue_share": Fact(
                    value=best["revenue"] / total_rev, unit="pct", label="porcentaje de la facturación"
                ),
                "growth": Fact(
                    value=growth, unit="pct", label="crecimiento de ventas (en pesos), 2da vs 1ra mitad"
                ),
            },
            impact_monthly=best["contribution"] / ctx.n_months * 0.1,  # escenario: +10% de ventas
        )
    ]


@detector()
def top_seller_low_margin(ctx: Context) -> list[Finding]:
    """Lo que más se vende no es lo que más deja."""
    p = ctx.by_method("mart_contribution_by_product")
    if p.empty:
        return []
    names = ctx.product_names()
    avg = p["contribution"].sum() / p["revenue"].sum()
    top = p.sort_values("revenue", ascending=False).iloc[0]
    if top["contribution_margin_pct"] >= avg:
        return []
    meaningful = p[p["revenue"] >= 0.02 * p["revenue"].sum()]
    best = meaningful.sort_values("contribution_margin_pct", ascending=False).iloc[0]
    tname, bname = (
        names.get(top["product_id"], top["product_id"]),
        names.get(best["product_id"], best["product_id"]),
    )
    return [
        Finding(
            key=f"top_seller_low_margin:{top['product_id']}",
            kind="top_seller_low_margin",
            category="diagnostico",
            severity="media",
            title=f"{tname} es lo que más vendés, pero no lo que más te deja",
            detail=(
                f"{tname} es [[top_share]] de la facturación pero deja [[top_margin]] después de gastos variables, "
                f"contra [[avg_margin]] del promedio del negocio. {bname} deja [[best_margin]]."
            ),
            entity_type="product",
            entity_id=top["product_id"],
            entity_name=tname,
            related_entities=[bname],
            facts={
                "top_share": Fact(
                    value=top["revenue"] / p["revenue"].sum(),
                    unit="pct",
                    label="participación en la facturación",
                ),
                "top_margin": Fact(
                    value=top["contribution_margin_pct"], unit="pct", label="margen del más vendido"
                ),
                "avg_margin": Fact(value=avg, unit="pct", label="margen promedio del negocio"),
                "best_margin": Fact(
                    value=best["contribution_margin_pct"],
                    unit="pct",
                    label="margen del producto que más deja",
                ),
            },
            depends_on_assumption=True,
        )
    ]


@detector("base_units", "min_3_months")
def nominal_growth_volume_decline(ctx: Context) -> list[Finding]:
    """Factura más en pesos pero vende menos volumen (efecto inflación)."""
    pnl = ctx.mart("mart_pnl_monthly").sort_values("period")
    k = 2 if len(pnl) >= 4 else 1
    first, last = pnl.head(k), pnl.tail(k)
    rev_chg = last["revenue"].mean() / first["revenue"].mean() - 1
    vol_chg = last["base_quantity"].mean() / first["base_quantity"].mean() - 1
    if not (rev_chg > 0 and vol_chg < 0):
        return []
    return [
        Finding(
            key="nominal_growth_volume_decline",
            kind="nominal_growth_volume_decline",
            category="diagnostico",
            severity="alta",
            title=f"Facturás más pesos, pero vendés menos {ctx.base_unit}",
            detail=(
                "Comparando el principio y el final del período, la facturación subió [[revenue_change]] "
                "pero el volumen bajó [[volume_change]]. La suba es por precios (inflación), no porque se venda más."
            ),
            facts={
                "revenue_change": Fact(value=rev_chg, unit="pct", label="variación de facturación en pesos"),
                "volume_change": Fact(
                    value=vol_chg, unit="pct", label=f"variación de volumen en {ctx.base_unit}"
                ),
            },
        )
    ]


@detector("named_customers")
def cross_sell(ctx: Context) -> list[Finding]:
    """Productos que dejan buen margen y que muchos clientes del canal todavía no compran."""
    cp = ctx.mart("mart_customer_product")
    margins = ctx.by_method("mart_contribution_by_channel_product")
    chan = ctx.by_method("mart_contribution_by_channel").set_index("channel")
    names = ctx.product_names()
    cust = ctx.customers().set_index("customer_id")
    out = []
    for ch, g in cp.groupby("channel"):
        customers = set(g["customer_id"])
        if len(customers) < ctx.t.cross_sell_min_non_buyers + 1:
            continue
        ch_margin = chan.loc[ch, "contribution_margin_pct"] if ch in chan.index else 0
        m = margins[margins["channel"] == ch].set_index("product_id")
        candidates = []
        for pid, pg in g.groupby("product_id"):
            buyers = set(pg["customer_id"])
            pen = len(buyers) / len(customers)
            non = customers - buyers
            if pid not in m.index:
                continue
            margin = m.loc[pid, "contribution_margin_pct"]
            if (
                pen >= ctx.t.cross_sell_min_penetration
                and len(non) >= ctx.t.cross_sell_min_non_buyers
                and margin > max(ch_margin, 0)
            ):
                rev_per_buyer = pg["revenue"].sum() / len(buyers) / ctx.n_months
                candidates.append((pid, buyers, non, margin, rev_per_buyer))
        if not candidates:
            continue
        pid, buyers, non, margin, rev_pb = max(candidates, key=lambda c: c[3] * len(c[2]) * c[4])
        pname = names.get(pid, pid)
        out.append(
            Finding(
                key=f"cross_sell:{ch}:{pid}",
                kind="cross_sell",
                category="accion",
                severity="baja",
                title=f"Ofrecer {pname} a {_channel_word(ch)} que todavía no lo compran",
                detail=(
                    "Ya lo compran [[buyers]] clientes del canal y deja [[margin]] después de gastos variables "
                    "(el canal promedia [[channel_margin]]). Hay [[non_buyers]] clientes que nunca lo pidieron."
                ),
                entity_type="product",
                entity_id=pid,
                entity_name=pname,
                related_entities=sorted(cust.loc[c, "customer_name"] for c in non if c in cust.index),
                facts={
                    "buyers": Fact(
                        value=len(buyers), unit="count", label="clientes del canal que ya lo compran"
                    ),
                    "non_buyers": Fact(
                        value=len(non), unit="count", label="clientes del canal que no lo compran"
                    ),
                    "margin": Fact(value=margin, unit="pct", label="margen del producto en el canal"),
                    "channel_margin": Fact(value=ch_margin, unit="pct", label="margen promedio del canal"),
                    "potential_monthly": Fact(
                        value=len(non) * rev_pb * 0.5 * margin,
                        unit="money",
                        label="ganancia mensual si la mitad lo empieza a comprar",
                    ),
                },
                impact_monthly=len(non) * rev_pb * 0.5 * margin,
            )
        )
    return out
