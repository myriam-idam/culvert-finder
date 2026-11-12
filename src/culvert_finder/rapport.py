"""Rapport HTML autonome (cartes, profil avant/après, tableau des franchissements)."""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from culvert_finder.mnt import profil_en_long  # noqa: E402
from culvert_finder.score import CLASSE_LIBRE, CLASSE_PROBABLE, CLASSE_VERIFIER  # noqa: E402

COULEURS = {CLASSE_PROBABLE: "#d62728", CLASSE_VERIFIER: "#ff7f0e", CLASSE_LIBRE: "#2ca02c"}


def _etendue(mnt, transform):
    h, w = mnt.shape
    return [transform.c, transform.c + w * transform.a, transform.f + h * transform.e, transform.f]


def ombrage(mnt: np.ndarray, res: float, azimut: float = 315, hauteur: float = 45) -> np.ndarray:
    gy, gx = np.gradient(np.nan_to_num(mnt, nan=np.nanmean(mnt)), res)
    pente = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(azimut), np.radians(hauteur)
    return np.clip(np.sin(alt) * np.sin(pente) + np.cos(alt) * np.cos(pente) * np.cos(az - aspect), 0, 1)


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def figure_carte(res) -> bytes:
    ext = _etendue(res.mnt, res.transform)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(ombrage(res.mnt, abs(res.transform.a)), cmap="gray", extent=ext, alpha=0.9)
    ax.imshow(res.mnt, cmap="terrain", extent=ext, alpha=0.35)
    if len(res.infrastructures):
        res.infrastructures.plot(ax=ax, color="#555555", linewidth=0.8)
    for ligne in res.lignes_cours_eau:
        ax.plot(*ligne.xy, color="#1f77b4", linewidth=1.4)
    f = res.franchissements
    for classe, couleur in COULEURS.items():
        sel = f[f["classe"] == classe]
        if len(sel):
            ax.scatter(sel.geometry.x, sel.geometry.y, s=55, c=couleur, edgecolor="black", zorder=5,
                       label=f"{classe} ({len(sel)})")
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_title("Franchissements cours d'eau × infrastructures")
    ax.legend(loc="lower left", fontsize=8)
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.tick_params(labelsize=7)
    return _png(fig)


def figure_cuvettes(res) -> bytes:
    ext = _etendue(res.mnt, res.transform)
    vmax = max(float(np.nanpercentile(res.profondeur_avant[res.profondeur_avant > 0], 99))
               if (res.profondeur_avant > 0).any() else 1.0, 0.1)
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), sharey=True)
    for ax, prof, titre in zip(axes, (res.profondeur_avant, res.profondeur_apres), ("MNT brut", "MNT corrigé")):
        ax.imshow(ombrage(res.mnt, abs(res.transform.a)), cmap="gray", extent=ext)
        im = ax.imshow(np.where(prof > 0.05, prof, np.nan), cmap="Blues", vmin=0, vmax=vmax, extent=ext)
        vol = np.nansum(prof) * abs(res.transform.a * res.transform.e)
        ax.set_title(f"{titre} — cuvettes : {vol:,.0f} m³".replace(",", " "))
        ax.ticklabel_format(useOffset=False, style="plain")
        ax.tick_params(labelsize=7)
    fig.colorbar(im, ax=axes, shrink=0.7, label="Profondeur d'eau stagnante (m)")
    return _png(fig)


def figure_profil(res) -> bytes | None:
    f = res.franchissements
    sel = f[f["corrige"]] if "corrige" in f else f.iloc[0:0]
    if not len(sel):
        return None
    ligne = sel.iloc[0]
    trace = res.lignes_cours_eau[int(ligne["indice_cours_eau"])]
    d = res.params.demi_longueur_profil * 1.5
    off, _, _, z_brut = profil_en_long(trace, ligne.geometry, res.mnt, res.transform, d)
    _, _, _, z_corr = profil_en_long(trace, ligne.geometry, res.mnt_corrige, res.transform, d)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(off, z_brut, color="#7f7f7f", label="MNT brut (remblai = faux barrage)")
    ax.plot(off, z_corr, color="#1f77b4", linewidth=2, label="MNT corrigé (ouvrage restitué)")
    ax.axvspan(-res.params.demi_largeur_remblai, res.params.demi_largeur_remblai, color="#ffdd99", alpha=0.4,
               label=ligne["type_infra"])
    ax.set_xlabel("Distance le long du cours d'eau (m)")
    ax.set_ylabel("Altitude (m)")
    ax.set_title(f"Profil en long au franchissement le plus probable (score {ligne['score']:.2f})")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    return _png(fig)


def _img(png: bytes | None, alt: str) -> str:
    if png is None:
        return ""
    return f'<img alt="{alt}" src="data:image/png;base64,{base64.b64encode(png).decode()}">'


def ecrire_rapport(res, sortie: str | Path) -> Path:
    sortie = Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    resume = res.resume()
    carte, cuvettes, profil = figure_carte(res), figure_cuvettes(res), figure_profil(res)
    for nom, png in (("carte.png", carte), ("cuvettes.png", cuvettes), ("profil.png", profil)):
        if png:
            (sortie / nom).write_bytes(png)

    f = res.franchissements
    colonnes = ["type_infra", "pont_bdtopo", "hauteur_remblai_m", "profondeur_cuvette_m", "score", "classe",
                "ouvrage_osm", "type_ouvrage_osm", "corrige"]
    lignes_html = []
    for i, r in f.head(50).iterrows():
        cells = [f"{r.geometry.x:.0f}", f"{r.geometry.y:.0f}"] + [html.escape(str(r[c])) for c in colonnes]
        style = f' style="border-left:4px solid {COULEURS.get(r["classe"], "#ccc")}"'
        lignes_html.append(f"<tr{style}><td>{i + 1}</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    entetes = "".join(f"<th>{c}</th>" for c in ["#", "X (L93)", "Y (L93)"] + colonnes)

    cartes_kpi = [
        ("Franchissements analysés", resume["franchissements"]),
        ("Ouvrages manquants probables", resume["par_classe"].get(CLASSE_PROBABLE, 0)),
        ("Dont confirmés par OSM", resume["confirmes_par_osm"]),
        ("Réduction du volume de cuvettes", f'{resume["reduction_volume_cuvettes_pct"]} %'),
    ]
    kpi = "".join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for k, v in cartes_kpi)

    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>culvert-finder — rapport</title>
<style>
body{{font-family:system-ui,Segoe UI,sans-serif;margin:0 auto;max-width:1100px;padding:16px;color:#222;background:#fff}}
h1{{margin-bottom:4px}} .kpis{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.kpi{{flex:1 1 200px;border:1px solid #ddd;border-radius:8px;padding:12px}} .kpi b{{display:block;font-size:1.8em}}
.kpi span{{color:#666;font-size:.9em}} img{{max-width:100%;height:auto;margin:8px 0}}
table{{border-collapse:collapse;font-size:.82em;width:100%}} th,td{{border-bottom:1px solid #eee;padding:4px 6px;text-align:left}}
.scroll{{overflow-x:auto}} .note{{color:#666;font-size:.9em}}
</style></head><body>
<h1>Rapport culvert-finder</h1>
<p class="note">Détection des ouvrages hydrauliques (buses, ponts) absents du MNT et correction du MNT
pour la modélisation hydraulique. Données : IGN (RGE ALTI, BD TOPO) — Licence Ouverte 2.0 ;
© contributeurs OpenStreetMap — ODbL.</p>
<div class="kpis">{kpi}</div>
<h2>Carte des franchissements</h2>{_img(carte, "Carte des franchissements")}
<h2>Profil en long avant / après correction</h2>{_img(profil, "Profil en long")}
<h2>Cuvettes artificielles avant / après correction</h2>{_img(cuvettes, "Cuvettes avant après")}
<h2>Franchissements (50 premiers, triés par score)</h2>
<div class="scroll"><table><thead><tr>{entetes}</tr></thead><tbody>{"".join(lignes_html)}</tbody></table></div>
<h2>Méthode</h2>
<ol class="note">
<li>Intersection des cours d'eau (BD TOPO) avec les routes et voies ferrées.</li>
<li>Profil en long du MNT le long du cours d'eau, accroché au point bas voisin (thalweg).</li>
<li><b>Hauteur de remblai</b> : point haut au droit de l'infrastructure moins le plus haut des points bas amont/aval.</li>
<li><b>Cuvette</b> : profondeur d'eau stagnante après comblement des dépressions du MNT.</li>
<li>Score = 60 % remblai + 40 % cuvette ; au-delà du seuil, un chenal est creusé dans le MNT.</li>
<li>Validation croisée avec les buses et ponts cartographiés dans OpenStreetMap.</li>
</ol>
</body></html>"""
    chemin = sortie / "rapport.html"
    chemin.write_text(page, encoding="utf-8")
    return chemin
