"""Correction du MNT : ouverture d'un chenal à travers les remblais détectés (« breaching »)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from culvert_finder.config import Parametres
from culvert_finder.mnt import lignes_colonnes, profil_en_long


def _point_bas(mnt: np.ndarray, r: int, c: int, k: int) -> tuple[int, int] | None:
    """Cellule la plus basse dans la fenêtre (2k+1)² centrée sur (r, c)."""
    r0, c0 = max(r - k, 0), max(c - k, 0)
    fen = mnt[r0 : r + k + 1, c0 : c + k + 1]
    if fen.size == 0 or not np.isfinite(fen).any():
        return None
    i, j = np.unravel_index(np.nanargmin(fen), fen.shape)
    return r0 + int(i), c0 + int(j)


def _relier(cellules: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Relie des cellules successives par des segments discrets (chemin 8-connexe sans doublon)."""
    chemin: list[tuple[int, int]] = []
    for (r0, c0), (r1, c1) in zip(cellules, cellules[1:] + cellules[-1:]):
        n = max(abs(r1 - r0), abs(c1 - c0)) + 1
        for r, c in zip(np.rint(np.linspace(r0, r1, n)).astype(int), np.rint(np.linspace(c0, c1, n)).astype(int)):
            if not chemin or chemin[-1] != (r, c):
                chemin.append((int(r), int(c)))
    return chemin


def creuser(
    mnt: np.ndarray,
    mnt_thalweg: np.ndarray,
    franch: gpd.GeoDataFrame,
    lignes: list[LineString],
    transform,
    params: Parametres,
) -> tuple[np.ndarray, np.ndarray]:
    """Ouvre un chenal dans le MNT au droit des franchissements dont le score dépasse le seuil.

    1. Sur le profil en long, on repère le point bas de chaque côté du remblai.
    2. On suit le thalweg réel (cellule la plus basse près du tracé BD TOPO, qui peut en
       être décalé de quelques mètres) du point bas le plus haut vers le plus bas.
    3. Le long de ce chemin, l'altitude est rendue non croissante (minimum cumulé) sans
       descendre sous le point bas d'arrivée : l'eau franchit le remblai comme par une buse.
       Seules les cellules qui bloquent l'écoulement sont abaissées ; le MNT n'est jamais relevé
       et aucun creux n'est créé.

    Renvoie (MNT corrigé, masque booléen des franchissements corrigés).
    """
    corrige = mnt.copy()
    corriges = np.zeros(len(franch), dtype=bool)
    k = max(0, int(round(params.rayon_thalweg / abs(transform.a))))
    w = params.demi_largeur_chenal
    c = params.demi_largeur_remblai
    h, larg = mnt.shape
    for n, (p, j, score) in enumerate(zip(franch.geometry, franch["indice_cours_eau"], franch["score"])):
        if score < params.seuil_correction:
            continue
        off, xs, ys, z = profil_en_long(lignes[int(j)], p, mnt_thalweg, transform, params.demi_longueur_profil)
        gauche = np.where((off < -c) & np.isfinite(z))[0]
        droite = np.where((off > c) & np.isfinite(z))[0]
        if not len(gauche) or not len(droite):
            continue
        ig, id_ = gauche[np.argmin(z[gauche])], droite[np.argmin(z[droite])]
        # On part du point bas le plus haut (amont hydraulique) vers le plus bas (aval)
        i_amont, i_aval = (ig, id_) if z[ig] >= z[id_] else (id_, ig)
        pas = 1 if i_aval > i_amont else -1
        indices = range(i_amont, i_aval + pas, pas)

        rows, cols = lignes_colonnes(transform, xs[list(indices)], ys[list(indices)])
        points = [_point_bas(mnt, r, col, k) for r, col in zip(rows, cols) if 0 <= r < h and 0 <= col < larg]
        points = [q for q in points if q is not None]
        if len(points) < 2:
            continue

        z_aval = mnt[points[-1]]
        courant = mnt[points[0]]
        for r, col in _relier(points):
            if not np.isfinite(mnt[r, col]):
                continue
            courant = min(courant, mnt[r, col])
            cible = max(courant, z_aval)
            bloc = corrige[max(r - w, 0) : r + w + 1, max(col - w, 0) : col + w + 1]
            np.fmin(bloc, cible, out=bloc, where=np.isfinite(bloc))
        corriges[n] = True
    return corrige, corriges
