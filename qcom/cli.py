"""Command-line entry points for the engine.

Examples:
    python -m qcom.cli simulate --orders-per-day 340 --batching 1
    python -m qcom.cli simulate --orders-per-day 520 --batching 2
    python -m qcom.cli demand --stores 8,8 4,4
    python -m qcom.cli place --stores 6
    python -m qcom.cli frontier --target-margin 0
    python -m qcom.cli sensitivity --n 32
"""
from __future__ import annotations

import argparse
import json

from qcom.costs import CostModel
from qcom.calibrate import calibrate_to_metro
from qcom.scenarios import tier2_config, metro_config, run_twin
from qcom.geo import GridCity
from qcom.demand import DemandModel
from qcom.place import FacilityLocator
from qcom.frontier import best_over_batching, frontier_curve, aov_only_strawman
from qcom.sensitivity import run_sobol


def _calibrated() -> CostModel:
    cal, _ = calibrate_to_metro(CostModel(), -3.02, 709, replications=8)
    return cal


def cmd_simulate(args) -> None:
    cost = _calibrated()
    cfg = tier2_config(orders_per_day=args.orders_per_day, batch_target=args.batching)
    t = run_twin(cfg, cost, aov=args.aov, ad_take=args.ad_take, replications=args.sims, seed=args.seed)
    print(json.dumps(t.as_dict(), indent=2, default=str))


def cmd_demand(args) -> None:
    city = GridCity.synthetic()
    dm = DemandModel(city)
    stores = [tuple(int(v) for v in s.split(",")) for s in args.stores]
    rates = dm.store_order_rates(stores)
    print(f"total population : {city.total_population():,.0f}")
    print(f"covered fraction : {dm.covered_demand_fraction(stores):.1%}")
    for sc, r in zip(stores, rates):
        print(f"  store {sc}: {r:,.0f} orders/day captured")


def cmd_place(args) -> None:
    city = GridCity.synthetic(n=14, cell_km=0.8)
    loc = FacilityLocator(city, service_km=args.service_km, candidate_stride=2)
    opt = loc.solve(args.stores, with_bound=True)
    naive = loc.equal_spacing(args.stores)
    print(f"optimized coverage : {opt.covered_fraction:.1%}")
    print(f"naive coverage     : {naive.covered_fraction:.1%}")
    print(f"LP upper bound     : {opt.lp_upper_bound:,.0f}")
    print(f"gap to LP bound    : {opt.optimality_gap:.1%}")
    print(f"store cells        : {opt.store_cells}")


def cmd_frontier(args) -> None:
    cost = _calibrated()
    res = best_over_batching(cost, target_margin=args.target_margin, replications=args.sims)
    print("best feasible configuration:")
    print(f"  batching      : {res.batch_target}")
    for k, v in res.levers.items():
        print(f"  {k:14s}: {v:.3f}")
    print(f"  contribution  : {res.contribution:.1f}/order")
    print(f"  SLA breach    : {res.sla_breach:.1%}")
    print("frontier curve (density -> required ad take):")
    for row in frontier_curve(cost, target_margin=args.target_margin, replications=args.sims):
        ad = row["required_ad_take"]
        ads = f"{ad:.1%}" if ad is not None else "INFEASIBLE"
        print(f"  {row['orders_per_day']:.0f} orders/day -> ad take {ads}")
    print("AOV-only strawman:")
    for row in aov_only_strawman(cost, replications=args.sims):
        print(f"  {row['orders_per_day']:.0f} orders/day @ AOV {row['aov']:.0f} -> "
              f"{row['contribution']:.1f}/order")


def cmd_sensitivity(args) -> None:
    cost = _calibrated()
    sob = run_sobol(cost, n=args.n, replications=args.sims)
    print("Sobol indices (variance attribution of contribution margin):")
    for name, s1, st in sob.ranked():
        print(f"  {name:16s}  first-order S1={s1:.3f}  total ST={st:.3f}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="qcom", description="Quick-commerce path-to-profit engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simulate", help="run the dark-store twin at a configuration")
    s.add_argument("--orders-per-day", type=float, default=340.0)
    s.add_argument("--batching", type=int, default=1)
    s.add_argument("--aov", type=float, default=560.0)
    s.add_argument("--ad-take", type=float, default=0.0)
    s.add_argument("--sims", type=int, default=12)
    s.add_argument("--seed", type=int, default=2)
    s.set_defaults(func=cmd_simulate)

    d = sub.add_parser("demand", help="gravity catchment for given store cells")
    d.add_argument("stores", nargs="+", help="store cells as i,j (e.g. 8,8 4,4)")
    d.set_defaults(func=cmd_demand)

    p = sub.add_parser("place", help="facility-location optimizer vs naive baseline")
    p.add_argument("--stores", type=int, default=6)
    p.add_argument("--service-km", type=float, default=2.0)
    p.set_defaults(func=cmd_place)

    fr = sub.add_parser("frontier", help="breakeven frontier + strawman")
    fr.add_argument("--target-margin", type=float, default=0.0)
    fr.add_argument("--sims", type=int, default=8)
    fr.set_defaults(func=cmd_frontier)

    se = sub.add_parser("sensitivity", help="Sobol global sensitivity")
    se.add_argument("--n", type=int, default=32)
    se.add_argument("--sims", type=int, default=3)
    se.set_defaults(func=cmd_sensitivity)
    return ap


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
