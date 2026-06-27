import sys
from pathlib import Path

"""
调用方法:
~/venvs/py313/bin/python \
'Brain dilated.py' \
--brain_nii_path='wmparc.nii.gz' \
--export_individual=False \
--dilation_iterations=5 \
--structure_size=5 \
&& \
/Applications/Blender.app/Contents/MacOS/Blender \
--background \
--python 'Blender scripting.py' \
-- \
--brain_ply_path='wmparc_all.ply' \
--end_frame=150
"""

def _script_dir():
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return Path.cwd()


SCRIPT_DIR = _script_dir()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from blender_gyrus_pipeline import parse_blender_cli_args, run_gyrus_pipeline


def main():
    args = parse_blender_cli_args()
    brain_ply = str(Path(args.brain_ply_path).expanduser())

    run_gyrus_pipeline(
        brain_ply_path=brain_ply,
        export_frame=args.end_frame,
        validate_brain_path=True,
        cloth_cache_end=args.end_frame,
        use_output_dir_fallback=True,
    )


main()
