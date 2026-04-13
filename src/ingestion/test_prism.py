"""Smoke test: verify FTP structure and download+clip for all 6 PRISM variables.

Downloads one file per variable from 1991 into a temp directory.
Run this before kicking off the full overnight ingest.
"""

import ftplib
import io
import tempfile
import zipfile
from pathlib import Path

import rasterio
from rasterio.mask import mask
from shapely.geometry import box, mapping

from ingest_prism import FTP_HOST, NAPA_BBOX, VARIABLES

PROBE_YEAR = 1991


def probe_variable(ftp: ftplib.FTP, var: str, tmpdir: Path) -> None:
    remote_dir = f"/time_series/us/an/4km/{var}/daily/{PROBE_YEAR}"

    files = ftp.nlst(remote_dir)
    zips = sorted(f for f in files if f.endswith(".zip"))

    if not zips:
        print(f"  [{var}] FAIL — no .zip files found in {remote_dir}")
        return

    print(f"  [{var}] {len(zips)} files on FTP for {PROBE_YEAR}")

    remote_path = zips[0]
    filename = Path(remote_path).name

    buf = io.BytesIO()
    ftp.retrbinary(f"RETR {remote_path}", buf.write)
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        tif_names = [n for n in names if n.endswith(".tif")]
        if not tif_names:
            print(f"  [{var}] FAIL — no .tif inside zip (found: {names})")
            return
        zf.extractall(tmpdir)

    tif_path = tmpdir / tif_names[0]
    out_path = tmpdir / (tif_path.stem + "_clipped.tif")
    napa_geom = [mapping(box(*NAPA_BBOX))]

    with rasterio.open(tif_path) as src:
        clipped, transform = mask(src, napa_geom, crop=True)
        profile = src.profile.copy()
        profile.update(height=clipped.shape[1], width=clipped.shape[2], transform=transform)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(clipped)

    print(f"  [{var}] OK — clipped shape {clipped.shape}, saved to {out_path.name}")


def main() -> None:
    print(f"Connecting to {FTP_HOST}...")
    with ftplib.FTP(FTP_HOST) as ftp:
        ftp.login()
        print(f"Connected. Probing {len(VARIABLES)} variables for year {PROBE_YEAR}.\n")
        with tempfile.TemporaryDirectory() as tmpdir:
            for var in VARIABLES:
                probe_variable(ftp, var, Path(tmpdir))

    print("\nDone. If all variables show OK, the overnight ingest is ready to run.")


if __name__ == "__main__":
    main()
