"""Ingest PRISM daily climate rasters for Napa Valley.

Downloads daily .bil files for each variable and year via FTP,
clips them to the Napa County bounding box, and writes them to
data/raw/prism/<var>/<year>/.
"""

import ftplib
import io
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import rasterio
from rasterio.mask import mask
from shapely.geometry import box, mapping

try:
    from .utils import DATA_RAW_DIR, log_load_summary
except ImportError:
    from utils import DATA_RAW_DIR, log_load_summary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Boundary Clipping for Napa Valley Climate Data
# West:  -122.67
# East:  -122.10
# South:  38.18
# North:  38.86

VARIABLES = ["tmin", "tmax", "tmean", "ppt", "vpdmin", "vpdmax"]
START_YEAR = 1991
FTP_HOST = "prism.nacse.org"
LOCAL_DIR = "data/raw/prism"
NAPA_BBOX = (-122.67, 38.18, -122.10, 38.86)  # (west, south, east, north)


# ---------------------------------------------------------------------------
# FTP helpers
# ---------------------------------------------------------------------------

def list_bil_zips(ftp: ftplib.FTP, var: str, year: int) -> list[str]:
    """Return sorted list of remote *_bil.zip paths for a variable/year directory.

    When both stable and provisional files exist for the same date, the stable
    file is preferred.

    Args:
        ftp: An open, logged-in FTP connection.
        var: PRISM variable name (e.g. 'tmax').
        year: Four-digit year.

    Returns:
        Sorted list of remote file paths (one per date, stable preferred).
    """
    remote_dir = f"/time_series/us/an/4km/{var}/daily/{year}/"
    try:
        files = ftp.nlst(remote_dir)
    except ftplib.error_perm:
        return []

    zips = [f for f in files if f.endswith(".zip")]

    # Key by date string, overwrite provisional entry with stable if both exist
    by_date: dict[str, str] = {}
    for filepath in zips:
        filename = Path(filepath).name
        date_match = re.search(r"(\d{8})", filename)
        if not date_match:
            continue
        date_str = date_match.group(1)
        if date_str not in by_date or "_stable_" in filename:
            by_date[date_str] = filepath

    return sorted(by_date.values())


# ---------------------------------------------------------------------------
# Local path derivation
# ---------------------------------------------------------------------------

def derive_output_path(var: str, year: int, zip_filename: str) -> Path:
    """Derive the local clipped .bil path for a given zip filename.

    Example:
        PRISM_tmax_stable_4kmD2_19810101_bil.zip
        -> data/raw/prism/tmax/1981/PRISM_tmax_stable_4kmD2_19810101.bil

    Args:
        var: PRISM variable name.
        year: Four-digit year.
        zip_filename: Basename of the remote zip file.

    Returns:
        Path where the clipped .bil should be saved locally.
    """
    stem = Path(zip_filename).stem        # e.g. prism_tmin_us_25m_19810919
    tif_name = stem + ".tif"
    return DATA_RAW_DIR / "prism" / var / str(year) / tif_name


# ---------------------------------------------------------------------------
# Download + clip
# ---------------------------------------------------------------------------

def download_and_clip(ftp: ftplib.FTP, remote_path: str, out_path: Path) -> None:
    """Download a zip from FTP, clip the .bil to NAPA_BBOX, and write to disk.

    The zip is downloaded into a BytesIO buffer (never written to disk as a zip)
    and extracted to a temporary directory that is cleaned up automatically.

    Args:
        ftp: An open, logged-in FTP connection.
        remote_path: Full remote path of the .zip file.
        out_path: Local destination for the clipped .bil file.
    """
    buf = io.BytesIO()
    ftp.retrbinary(f"RETR {remote_path}", buf.write)
    buf.seek(0)

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(buf) as zf:
            zf.extractall(tmpdir)

        tif_files = list(Path(tmpdir).glob("*.tif"))
        if not tif_files:
            raise FileNotFoundError(f"No .tif file found inside {remote_path}")
        bil_file = tif_files[0]

        napa_geom = [mapping(box(*NAPA_BBOX))]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(bil_file) as src:
            clipped, transform = mask(src, napa_geom, crop=True)
            profile = src.profile.copy()
            profile.update(
                height=clipped.shape[1],
                width=clipped.shape[2],
                transform=transform,
            )
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(clipped)


# ---------------------------------------------------------------------------
# Main ingestion loop
# ---------------------------------------------------------------------------

def ingest_prism(
    variables: list[str] = VARIABLES,
    start_year: int = START_YEAR,
    end_year: Optional[int] = None,
) -> None:
    """Download and clip PRISM daily rasters for the given variables and year range.

    Already-clipped files are skipped so re-runs are safe. A summary of newly
    downloaded files is printed via log_load_summary at the end.

    Args:
        variables: List of PRISM variables to ingest.
        start_year: First year to ingest (inclusive).
        end_year: Last year to ingest (inclusive). Defaults to the current year.
    """
    if end_year is None:
        end_year = datetime.today().year

    records: list[dict] = []

    with ftplib.FTP(FTP_HOST) as ftp:
        ftp.login()
        print(f"Connected to {FTP_HOST}")

        for var in variables:
            for year in range(start_year, end_year + 1):
                bil_zips = list_bil_zips(ftp, var, year)
                print(f"  {var}/{year}: {len(bil_zips)} files on FTP")

                for remote_path in bil_zips:
                    zip_filename = Path(remote_path).name
                    out = derive_output_path(var, year, zip_filename)

                    if out.exists():
                        continue  # idempotency: already clipped

                    try:
                        download_and_clip(ftp, remote_path, out)
                    except Exception as exc:
                        print(f"    [WARN] skipped {zip_filename}: {exc}")
                        continue

                    date_match = re.search(r"(\d{8})", zip_filename)
                    date_str = date_match.group(1) if date_match else None
                    try:
                        date = datetime.strptime(date_str, "%Y%m%d").date() if date_str else None
                    except ValueError:
                        date = None

                    records.append({"variable": var, "date": date, "file": str(out)})
                    print(f"    saved {out.name}")

    if records:
        summary_df = pd.DataFrame(records)
        log_load_summary(summary_df, "PRISM")
    else:
        print("[PRISM] no new files downloaded")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest PRISM daily rasters for Napa Valley.")
    parser.add_argument(
        "--variable",
        dest="variables",
        action="append",
        choices=VARIABLES,
        metavar="VAR",
        help=f"Variable to ingest (one of: {', '.join(VARIABLES)}). "
             "Repeat to ingest multiple. Defaults to all variables.",
    )
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--apply", action="store_true", help="No-op flag kept for compatibility.")
    args = parser.parse_args()

    ingest_prism(
        variables=args.variables or VARIABLES,
        start_year=args.start_year,
        end_year=args.end_year,
    )
