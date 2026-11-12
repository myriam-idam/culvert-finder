"""Outils raster : comblement des cuvettes, recherche du thalweg, profils en long."""

from __future__ import annotations

import numpy as np
from scipy import ndimage
from shapely.geometry import LineString, Point
from skimage.morphology import reconstruction


def combler_cuvettes(mnt: np.ndarray) -> np.ndarray:
    """Comble les cuvettes du MNT par reconstruction morphologique (Soille, 2004).

    Les bords de la grille et les cellules sans donnée servent d'exutoires.
    """
    nan = np.isnan(mnt)
    if nan.all():
        return mnt.copy()
    travail = mnt.astype("float64").copy()
    travail[nan] = np.nanmin(mnt) - 1.0
    graine = np.full_like(travail, travail.max())
    graine[0, :], graine[-1, :] = travail[0, :], travail[-1, :]
    graine[:, 0], graine[:, -1] = travail[:, 0], travail[:, -1]
    graine[nan] = travail[nan]
    comble = reconstruction(graine, travail, method="erosion")
    comble[nan] = np.nan
    return comble


def profondeur_cuvettes(mnt: np.ndarray) -> np.ndarray:
    """Hauteur d'eau qui stagnerait dans chaque cellule (MNT comblé - MNT)."""
    return combler_cuvettes(mnt) - mnt


def mnt_thalweg(mnt: np.ndarray, rayon_cellules: int) -> np.ndarray:
    """Minimum local du MNT : « accroche » le tracé vectoriel au point bas voisin."""
    if rayon_cellules <= 0:
        return mnt.copy()
    nan = np.isnan(mnt)
    m = ndimage.minimum_filter(np.where(nan, np.inf, mnt), size=2 * rayon_cellules + 1, mode="nearest")
    m[np.isinf(m) | nan] = np.nan
    return m


def lignes_colonnes(transform, xs, ys):
    """Coordonnées -> indices (ligne, colonne) de la grille."""
    cols, rows = ~transform * (np.asarray(xs), np.asarray(ys))
    return np.floor(rows).astype(int), np.floor(cols).astype(int)


def echantillonner(grille: np.ndarray, transform, xs, ys) -> np.ndarray:
    rows, cols = lignes_colonnes(transform, xs, ys)
    ok = (rows >= 0) & (rows < grille.shape[0]) & (cols >= 0) & (cols < grille.shape[1])
    z = np.full(len(rows), np.nan)
    z[ok] = grille[rows[ok], cols[ok]]
    return z


def profil_en_long(ligne: LineString, point: Point, grille: np.ndarray, transform, demi_longueur: float):
    """Profil en long le long du cours d'eau, centré sur le point.

    Renvoie (abscisses relatives, xs, ys, z). Le pas est la résolution de la grille.
    """
    pas = abs(transform.a)
    d0 = ligne.project(point)
    d = np.arange(d0 - demi_longueur, d0 + demi_longueur + pas / 2, pas)
    d = d[(d >= 0) & (d <= ligne.length)]
    pts = [ligne.interpolate(v) for v in d]
    xs = np.array([p.x for p in pts])
    ys = np.array([p.y for p in pts])
    return d - d0, xs, ys, echantillonner(grille, transform, xs, ys)


def nanmax(a) -> float:
    a = np.asarray(a, dtype=float)
    return float(np.nanmax(a)) if np.isfinite(a).any() else np.nan


def nanmin(a) -> float:
    a = np.asarray(a, dtype=float)
    return float(np.nanmin(a)) if np.isfinite(a).any() else np.nan
