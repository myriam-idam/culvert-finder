"""Interface en ligne de commande."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from culvert_finder.config import Parametres


def _emprise_depuis_point(lon: float, lat: float, taille: float):
    from pyproj import Transformer

    x, y = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform(lon, lat)
    d = taille / 2
    return (round(x - d), round(y - d), round(x + d), round(y + d))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="culvert-finder",
        description="Détecte les ouvrages hydrauliques absents du MNT et corrige le MNT.",
    )
    sub = parser.add_subparsers(dest="commande", required=True)

    a = sub.add_parser("analyse", help="Analyse une zone réelle (données IGN + OSM)")
    zone = a.add_mutually_exclusive_group()
    zone.add_argument("--emprise", nargs=4, type=float, metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
                      help="Emprise en Lambert 93 (EPSG:2154)")
    zone.add_argument("--point", nargs=2, type=float, metavar=("LON", "LAT"),
                      help="Centre de la zone en WGS84 (degrés)")
    a.add_argument("--taille", type=float, default=2000, help="Côté de la zone autour de --point (m)")
    a.add_argument("--mnt", help="MNT local (GeoTIFF en Lambert 93, ex. dalle LiDAR HD) au lieu du RGE ALTI")
    a.add_argument("--resolution", type=float, default=1.0, help="Résolution du MNT téléchargé (m)")
    a.add_argument("--sans-osm", action="store_true", help="Ne pas interroger OpenStreetMap")
    a.add_argument("--seuil", type=float, default=0.6, help="Score minimal pour corriger le MNT")
    a.add_argument("--sortie", default="sortie", help="Dossier de sortie")

    d = sub.add_parser("demo", help="Démonstration hors ligne sur une scène synthétique")
    d.add_argument("--sortie", default="sortie_demo", help="Dossier de sortie")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    if args.commande == "demo":
        from culvert_finder.pipeline import analyser, sauvegarder
        from culvert_finder.rapport import ecrire_rapport
        from culvert_finder.synthetique import scene

        mnt, transform, cours_eau, infras, osm = scene()
        res = analyser(mnt, transform, cours_eau, infras, osm)
        sortie = Path(args.sortie)
        sortie.mkdir(parents=True, exist_ok=True)
        sauvegarder(res, sortie, cours_eau, osm)
        chemin = ecrire_rapport(res, sortie)
    else:
        from culvert_finder.pipeline import executer

        if args.point:
            emprise = _emprise_depuis_point(*args.point, args.taille)
        elif args.emprise:
            emprise = tuple(args.emprise)
        elif args.mnt:
            emprise = None
        else:
            parser.error("indiquez --emprise, --point ou --mnt")
        res = executer(args.sortie, emprise, args.mnt, args.resolution, not args.sans_osm,
                       Parametres(seuil_correction=args.seuil))
        chemin = Path(args.sortie) / "rapport.html"

    print(json.dumps(res.resume(), indent=2, ensure_ascii=False))
    print(f"\nRapport : {chemin.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
