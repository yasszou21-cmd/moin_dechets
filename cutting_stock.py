"""
Cutting Stock Solver
=====================
Résout le problème de découpe 1D : étant donné une barre standard de longueur L
et une liste de pièces (longueur, quantité) à découper, trouver le nombre
minimum de barres nécessaires et comment découper chacune.

Deux méthodes disponibles :
  1. solve_bfd()      -> heuristique "Best Fit Decreasing", rapide, résultat
                          approximatif (souvent 0 à 10% au-dessus de l'optimal).
  2. solve_optimal()  -> solveur exact via OR-Tools CP-SAT, garantit le nombre
                          minimum de barres (peut être plus lent sur de gros
                          volumes, d'où l'usage de solve_bfd() comme borne
                          supérieure pour accélérer la recherche).
"""

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class Piece:
    length: float
    quantity: int
    label: str = ""  # ex: "A", "Piece-1", nom donné par l'utilisateur

    def __post_init__(self):
        if not self.label:
            self.label = f"{self.length}"


@dataclass
class Bin:
    """Représente une barre standard découpée."""
    capacity: float
    cuts: List[float] = field(default_factory=list)   # longueurs coupées dans cette barre
    labels: List[str] = field(default_factory=list)   # étiquettes correspondantes

    @property
    def used(self) -> float:
        return sum(self.cuts)

    @property
    def waste(self) -> float:
        return self.capacity - self.used

    def can_fit(self, length: float) -> bool:
        return self.used + length <= self.capacity + 1e-9

    def add(self, length: float, label: str):
        self.cuts.append(length)
        self.labels.append(label)


def _expand_pieces(pieces: List[Piece]) -> List[Piece]:
    """Transforme la liste (longueur, quantité) en une liste d'unités individuelles,
    triée du plus grand au plus petit (nécessaire pour Decreasing)."""
    units = []
    for p in pieces:
        for _ in range(p.quantity):
            units.append(p)
    units.sort(key=lambda p: p.length, reverse=True)
    return units


def solve_bfd(bar_length: float, pieces: List[Piece]) -> List[Bin]:
    """Best Fit Decreasing : place chaque pièce (en partant de la plus grande)
    dans la barre déjà ouverte où il restera le MOINS de place après coupe.
    Si aucune barre ne peut l'accueillir, on ouvre une nouvelle barre."""
    units = _expand_pieces(pieces)
    bins: List[Bin] = []

    for p in units:
        if p.length > bar_length + 1e-9:
            raise ValueError(
                f"La pièce '{p.label}' ({p.length}m) est plus longue que la barre ({bar_length}m)."
            )

        best_bin = None
        best_remaining = None
        for b in bins:
            if b.can_fit(p.length):
                remaining_after = b.waste - p.length
                if best_remaining is None or remaining_after < best_remaining:
                    best_bin = b
                    best_remaining = remaining_after

        if best_bin is not None:
            best_bin.add(p.length, p.label)
        else:
            new_bin = Bin(capacity=bar_length)
            new_bin.add(p.length, p.label)
            bins.append(new_bin)

    return bins


def solve_optimal(bar_length: float, pieces: List[Piece], time_limit_s: int = 20) -> List[Bin]:
    """Solveur exact avec OR-Tools CP-SAT.
    Utilise le résultat de BFD comme borne supérieure sur le nombre de barres
    pour réduire l'espace de recherche.
    Nécessite : pip install ortools
    """
    from ortools.sat.python import cp_model

    # Borne supérieure = résultat heuristique BFD (toujours faisable)
    upper_bound_bins = solve_bfd(bar_length, pieces)
    max_bins = len(upper_bound_bins)

    if max_bins == 0:
        return []

    types = pieces  # chaque élément a length + quantity
    n_types = len(types)

    model = cp_model.CpModel()

    # x[b][i] = nombre de pièces de type i placées dans la barre b
    x = {}
    for b in range(max_bins):
        for i in range(n_types):
            x[b, i] = model.NewIntVar(0, types[i].quantity, f"x_{b}_{i}")

    # y[b] = 1 si la barre b est utilisée
    y = [model.NewBoolVar(f"y_{b}") for b in range(max_bins)]

    # Contrainte : la demande de chaque type de pièce doit être exactement satisfaite
    for i in range(n_types):
        model.Add(sum(x[b, i] for b in range(max_bins)) == types[i].quantity)

    # Contrainte : la longueur totale coupée dans une barre ne dépasse pas bar_length,
    # et seulement si la barre est "utilisée" (y[b] == 1)
    # CP-SAT a besoin d'entiers : comme les longueurs sont maintenant saisies
    # directement en millimètres (unité déjà entière côté usine), scale=1 suffit.
    # (Si un jour l'unité redevient le mètre avec décimales, remettre scale=1000.)
    scale = 1
    bar_length_int = round(bar_length * scale)
    for b in range(max_bins):
        model.Add(
            sum(round(types[i].length * scale) * x[b, i] for i in range(n_types))
            <= bar_length_int * y[b]
        )

    # Casser la symétrie : les barres utilisées sont "regroupées" en premier
    for b in range(max_bins - 1):
        model.Add(y[b] >= y[b + 1])

    # Objectif : minimiser le nombre de barres utilisées
    model.Minimize(sum(y))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Ne devrait pas arriver puisque BFD fournit déjà une solution faisable
        return upper_bound_bins

    result_bins: List[Bin] = []
    for b in range(max_bins):
        if solver.Value(y[b]) == 0:
            continue
        bn = Bin(capacity=bar_length)
        for i in range(n_types):
            count = solver.Value(x[b, i])
            for _ in range(count):
                bn.add(types[i].length, types[i].label)
        result_bins.append(bn)

    return result_bins


def solve_from_chutes(chutes: List[Piece], pieces: List[Piece], time_limit_s: int = 30) -> Dict:
    """Découpe des pièces demandées à partir d'un stock FIXE et hétérogène de
    chutes (chaque chute a sa propre longueur et une quantité disponible).

    Contrairement à solve_optimal() (barres neuves, illimitées, longueur unique),
    ici le stock est limité : il peut être impossible de satisfaire toute la
    demande. Deux cas :

    CAS 1 - Réalisable : toute la demande peut être satisfaite avec les chutes
        disponibles -> on minimise le déchet (= on utilise le moins de matière
        possible parmi les chutes, quitte à en laisser certaines intactes).
    CAS 2 - Irréalisable : la demande dépasse ce que permettent les chutes
        -> on utilise un maximum de chutes pour couper le plus grand nombre
        de pièces possible (sans dépasser la quantité demandée par type),
        et on indique le manque restant par type de pièce.

    Retourne un dict :
        {
          "feasible": bool,
          "bins": List[Bin],              # chutes effectivement utilisées et leur découpe
          "shortfall": Dict[str, int],     # manque par label de pièce (vide si feasible=True)
        }
    """
    from ortools.sat.python import cp_model

    chute_units = _expand_pieces(chutes)  # une ligne par chute physique disponible
    n_chutes = len(chute_units)
    n_types = len(pieces)

    if n_chutes == 0 or n_types == 0:
        return {"feasible": False, "bins": [], "shortfall": {p.label: p.quantity for p in pieces}}

    # ---------- CAS 1 : tenter de tout satisfaire en minimisant le déchet ----------
    model = cp_model.CpModel()
    x = {}
    for c in range(n_chutes):
        for i in range(n_types):
            max_par_chute = int(chute_units[c].length // pieces[i].length) if pieces[i].length > 0 else 0
            borne = min(pieces[i].quantity, max_par_chute)
            x[c, i] = model.NewIntVar(0, max(borne, 0), f"x_{c}_{i}")

    for c in range(n_chutes):
        model.Add(sum(round(pieces[i].length) * x[c, i] for i in range(n_types)) <= round(chute_units[c].length))

    for i in range(n_types):
        model.Add(sum(x[c, i] for c in range(n_chutes)) == pieces[i].quantity)

    y = [model.NewBoolVar(f"y_{c}") for c in range(n_chutes)]
    for c in range(n_chutes):
        max_pieces_possible = sum(
            min(pieces[i].quantity, int(chute_units[c].length // pieces[i].length) if pieces[i].length > 0 else 0)
            for i in range(n_types)
        )
        model.Add(sum(x[c, i] for i in range(n_types)) <= max_pieces_possible * y[c])

    # Minimiser la matière totale consommée (= minimiser le déchet, la demande étant fixe)
    model.Minimize(sum(round(chute_units[c].length) * y[c] for c in range(n_chutes)))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        bins = []
        for c in range(n_chutes):
            if solver.Value(y[c]) == 0:
                continue
            bn = Bin(capacity=chute_units[c].length)
            for i in range(n_types):
                for _ in range(solver.Value(x[c, i])):
                    bn.add(pieces[i].length, pieces[i].label)
            bins.append(bn)
        return {"feasible": True, "bins": bins, "shortfall": {}}

    # ---------- CAS 2 : irréalisable -> maximiser le nombre de pièces coupées ----------
    model2 = cp_model.CpModel()
    x2 = {}
    for c in range(n_chutes):
        for i in range(n_types):
            max_par_chute = int(chute_units[c].length // pieces[i].length) if pieces[i].length > 0 else 0
            borne = min(pieces[i].quantity, max_par_chute)
            x2[c, i] = model2.NewIntVar(0, max(borne, 0), f"x2_{c}_{i}")

    for c in range(n_chutes):
        model2.Add(sum(round(pieces[i].length) * x2[c, i] for i in range(n_types)) <= round(chute_units[c].length))

    for i in range(n_types):
        model2.Add(sum(x2[c, i] for c in range(n_chutes)) <= pieces[i].quantity)

    model2.Maximize(sum(x2[c, i] for c in range(n_chutes) for i in range(n_types)))

    solver2 = cp_model.CpSolver()
    solver2.parameters.max_time_in_seconds = time_limit_s
    solver2.parameters.num_search_workers = 8
    status2 = solver2.Solve(model2)

    bins = []
    produit_par_type = {i: 0 for i in range(n_types)}
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in range(n_chutes):
            compte = sum(solver2.Value(x2[c, i]) for i in range(n_types))
            if compte == 0:
                continue
            bn = Bin(capacity=chute_units[c].length)
            for i in range(n_types):
                v = solver2.Value(x2[c, i])
                produit_par_type[i] += v
                for _ in range(v):
                    bn.add(pieces[i].length, pieces[i].label)
            bins.append(bn)

    shortfall = {
        pieces[i].label: pieces[i].quantity - produit_par_type[i]
        for i in range(n_types)
        if pieces[i].quantity - produit_par_type[i] > 0
    }

    return {"feasible": False, "bins": bins, "shortfall": shortfall}


def summarize(bins: List[Bin]) -> Dict:
    total_waste = sum(b.waste for b in bins)
    total_used = sum(b.used for b in bins)
    total_capacity = sum(b.capacity for b in bins)
    return {
        "nb_barres": len(bins),
        "dechet_total": round(total_waste, 3),
        "taux_dechet_pct": round(100 * total_waste / total_capacity, 2) if bins else 0,
        "matiere_utilisee": round(total_used, 3),
    }


if __name__ == "__main__":
    # Exemple simple pour test rapide en ligne de commande
    bar_length = 12.0
    pieces = [
        Piece(length=5.0, quantity=7, label="A (5m)"),
        Piece(length=4.0, quantity=5, label="B (4m)"),
        Piece(length=3.0, quantity=6, label="C (3m)"),
        Piece(length=2.0, quantity=4, label="D (2m)"),
    ]

    print("=== BFD (heuristique) ===")
    bfd_bins = solve_bfd(bar_length, pieces)
    for idx, b in enumerate(bfd_bins, 1):
        print(f"Barre {idx}: {b.labels} | utilisé={b.used:.2f}m | déchet={b.waste:.2f}m")
    print(summarize(bfd_bins))
