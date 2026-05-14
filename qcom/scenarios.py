"""Market regimes, roster provisioning, and the integrated twin economics.

Ties the three model layers together:

  * `provision` sizes the picker and rider rosters to the *evening peak* (with a
    minimum-staffing floor), which is how real operators staff. The floor is the
    structural source of the tier-2 hole: a sparse store still needs a minimum
    crew that sits idle off-peak, so its fixed cost is spread over too few orders.
  * `run_twin` runs the discrete-event simulation, then feeds the *realized*
    per-order rider and picking cost into the contribution-margin model, so the
    unit economics reflect the actual queueing and routing, not an average.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from qcom.costs import CostModel, OrderEconomics
from qcom.desim import DEFAULT_HOURLY_WEIGHTS, DarkStoreSim, SimConfig, SimResult


@dataclass
class TwinResult:
    """Operational + economic outcome of one configuration."""

    sim: SimResult
    econ: OrderEconomics
    n_pickers: int
    n_riders: int

    @property
    def contribution(self) -> float:
        return self.econ.contribution

    def as_dict(self) -> dict:
        d = {"n_pickers": self.n_pickers, "n_riders": self.n_riders}
        d.update({f"sim_{k}": v for k, v in self.sim.as_dict().items()})
        d.update({f"econ_{k}": v for k, v in self.econ.as_dict().items()})
        d["contribution"] = self.contribution
        return d


def _peak_per_min(orders_per_day: float, open_hours: float) -> float:
    w = DEFAULT_HOURLY_WEIGHTS
    hour_len = open_hours * 60.0 / len(w)
    peak_hour_orders = orders_per_day * w.max() / w.sum()
    return peak_hour_orders / hour_len


def provision(
    cfg: SimConfig,
    target_peak_util: float = 0.82,
    min_pickers: int = 2,
    min_riders: int = 4,
) -> SimConfig:
    """Size pickers and riders to the peak with a minimum-staffing floor.

    Picker service: one picker clears 1/mean_pick orders per minute.
    Rider service: a single trip (out + back + handover) at the configured speed;
    batching divides the effective trip rate per order by the batch size.
    """
    peak = _peak_per_min(cfg.orders_per_day, cfg.open_hours)

    pick_rate_per_picker = 1.0 / cfg.mean_pick_min  # orders/min/picker
    n_pickers = max(min_pickers, math.ceil(peak / (pick_rate_per_picker * target_peak_util)))

    speed_km_per_min = cfg.rider_speed_kmph / 60.0
    single_trip_min = 2.0 * cfg.mean_drop_km / speed_km_per_min + cfg.handover_min
    # With batching, one trip serves up to batch_target drops; per-order trip time
    # is the multi-drop trip amortised over the batch (return leg shared).
    b = max(1, cfg.batch_target)
    per_order_trip_min = single_trip_min / b + (b - 1) * cfg.handover_min / b
    rider_throughput_per_min = 1.0 / per_order_trip_min
    n_riders = max(min_riders, math.ceil(peak / (rider_throughput_per_min * target_peak_util)))

    return replace(cfg, n_pickers=n_pickers, n_riders=n_riders)


def run_twin(
    cfg: SimConfig,
    cost: CostModel,
    aov: float,
    ad_take: float = 0.0,
    replications: int = 20,
    seed: int = 0,
    auto_provision: bool = True,
) -> TwinResult:
    """Run the discrete-event store, then price its realized operations."""
    if auto_provision:
        cfg = provision(cfg)
    sim = DarkStoreSim(cfg, seed=seed).run(replications=replications)
    econ = cost.economics(
        orders_per_day=sim.orders_delivered,
        aov=aov,
        batching=cfg.batch_target,
        ad_take=ad_take,
        rider_cost_per_order=sim.rider_cost_per_order,
        picking_cost_per_order=sim.picking_cost_per_order,
    )
    return TwinResult(sim=sim, econ=econ, n_pickers=cfg.n_pickers, n_riders=cfg.n_riders)


# ---- canonical market regimes (calibration-grade defaults) ----

def metro_config(orders_per_day: float = 1500.0) -> SimConfig:
    """A dense metro store: short drops, fast riders, high volume."""
    return SimConfig(
        orders_per_day=orders_per_day,
        mean_drop_km=0.9,
        rider_speed_kmph=22.0,
        mean_pick_min=2.6,
        handover_min=1.5,
        sla_min=15.0,
    )


def tier2_config(orders_per_day: float = 340.0, batch_target: int = 1) -> SimConfig:
    """A sparse tier-2 store: longer drops, slower roads, low volume."""
    return SimConfig(
        orders_per_day=orders_per_day,
        mean_drop_km=1.7,
        rider_speed_kmph=18.0,
        mean_pick_min=2.8,
        handover_min=2.0,
        batch_target=batch_target,
        sla_min=15.0,
    )
