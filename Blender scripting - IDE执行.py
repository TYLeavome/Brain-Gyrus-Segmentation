import sys
from pathlib import Path


BRAIN_PLY = "/Users/tianye/Downloads/wmparc_all.ply"
EXPORT_FRAME = 150
SCALE = 0.05


def _script_dir():
    if "__file__" in globals():
        return Path(__file__).resolve().parent

    try:
        import bpy

        text = getattr(getattr(bpy.context, "space_data", None), "text", None)
        filepath = getattr(text, "filepath", "")
        if filepath:
            return Path(filepath).resolve().parent
    except Exception:
        pass

    return Path.cwd()


SCRIPT_DIR = _script_dir()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from blender_gyrus_pipeline import run_gyrus_pipeline


def main():
    run_gyrus_pipeline(
        brain_ply_path=BRAIN_PLY,
        export_frame=EXPORT_FRAME,
        scale=float(SCALE),
        validate_brain_path=True,
        cloth_cache_end=EXPORT_FRAME,
        use_output_dir_fallback=True,
    )


main()
