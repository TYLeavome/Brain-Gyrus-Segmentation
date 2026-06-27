# -*- coding: utf-8 -*-

import os
import argparse
import numpy as np
import nibabel as nib
from pathlib import Path
from skimage.measure import marching_cubes
from scipy.ndimage import binary_dilation
from scipy.ndimage import binary_erosion

def _write_ply_ascii(ply_path: Path, vertices: np.ndarray, faces: np.ndarray) -> None:
    
    '''
    Write an ASCII PLY with vertices (N,3) and faces (M,3).
    '''

    ply_path.parent.mkdir(parents=True, exist_ok=True)

    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)

    header = [
        "ply",
        "format ascii 1.0",
        f"element vertex {v.shape[0]}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {f.shape[0]}",
        "property list uchar int vertex_indices",
        "end_header",
    ]

    with ply_path.open("w", encoding="utf-8") as fp:
        fp.write("\n".join(header) + "\n")
        for x, y, z in v:
            fp.write(f"{x} {y} {z}\n")
        for a, b, c in f:
            fp.write(f"3 {int(a)} {int(b)} {int(c)}\n")

def _mask_to_mesh_world(mask: np.ndarray, affine: np.ndarray, level: float = 0.5):
    
    '''
    Convert a binary mask (bool/0-1) to a surface mesh in world coordinates.
    Returns (vertices_world, faces).
    '''
    
    if mask.dtype != np.bool_:
        mask = mask.astype(bool)

    if mask.ndim != 3:
        raise ValueError(f"Only 3D volumes are supported, got mask.ndim={mask.ndim}")

    if not np.any(mask):
        return None, None

    verts_ijk, faces, _, _ = marching_cubes(
        volume=mask.astype(np.uint8),
        level=level,
        allow_degenerate=False,
    )

    ones = np.ones((verts_ijk.shape[0], 1), dtype=np.float64)
    verts_h = np.concatenate([verts_ijk.astype(np.float64), ones], axis=1)
    verts_world = (affine @ verts_h.T).T[:, :3]

    return verts_world, faces

def nii2ply(nii_path: str, export_individual: bool = False):

    '''
    输入:
    - nii_path: 一个 nifti 目录路径 (也兼容直接传入 .nii/.nii.gz 文件路径)
    - export_individual:
        True  -> 输出每个非零体素值对应的独立 .ply, 同时输出 all.ply
        False -> 只输出 all.ply

    操作:
    1. 读取 nii 的 data, 检查有多少种不同的体素值 (0 除外)
    2. 根据 export_individual 控制是否导出各个单独区域
    3. 始终导出一个 原文件名_all.ply (所有非零体素)
    '''

    p = Path(nii_path)

    if p.is_file() and (p.suffix == ".nii" or p.name.endswith(".nii.gz")):
        nii_file = p
        nii_dir = p.parent
    else:
        nii_dir = p
        if not nii_dir.exists() or not nii_dir.is_dir():
            raise FileNotFoundError(f"Not a directory or nifti file: {nii_path}")

        nii_candidates = sorted(list(nii_dir.glob("*.nii")) + list(nii_dir.glob("*.nii.gz")))
        if len(nii_candidates) == 0:
            raise FileNotFoundError(f"No .nii/.nii.gz found in directory: {nii_dir}")
        if len(nii_candidates) > 1:
            print(f"Found multiple nifti files, using the first one: {nii_candidates[0].name}")
        nii_file = nii_candidates[0]

    # 输出目录改为 NIfTI 文件所在目录
    out_dir = nii_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    img = nib.load(str(nii_file))
    data = img.get_fdata(dtype=np.float32)
    affine = img.affine

    # 提取原文件名 (去掉 .nii 或 .nii.gz)
    base_name = nii_file.name
    if base_name.endswith(".nii.gz"):
        base_name = base_name[:-7]
    elif base_name.endswith(".nii"):
        base_name = base_name[:-4]

    unique_vals = np.unique(data)
    nonzero_vals = unique_vals[unique_vals != 0]

    if nonzero_vals.size == 0:
        print("No non-zero voxel values found. Nothing to export.")
        return

    exported = []

    if export_individual:
        for v in nonzero_vals:
            label_int = int(round(float(v)))
            mask = (data == v)

            verts_world, faces = _mask_to_mesh_world(mask, affine)
            if verts_world is None:
                print(f"Skip value={v}: empty mask.")
                continue

            ply_path = out_dir / f"{base_name}_{label_int}.ply"
            if verts_world is not None and faces is not None:
                _write_ply_ascii(ply_path, verts_world, faces)
            exported.append(str(ply_path))

    all_mask = data != 0
    verts_world, faces = _mask_to_mesh_world(all_mask, affine)
    if verts_world is not None and faces is not None:
        all_path = out_dir / f"{base_name}_all.ply"
        _write_ply_ascii(all_path, verts_world, faces)
        exported.append(str(all_path))

    print("Exported PLY files:")
    for x in exported:
        print(f"- {x}")

def nii_dilation(nii_path: str,
                 dilation_iterations: int = 5,
                 structure_size: int = 5):

    '''
    输入:
    - nii_path: 单个 .nii 或 .nii.gz 文件路径
    - dilation_iterations: 膨胀次数
    - structure_size: 结构元素大小 (必须为奇数, 如 3,5,7)

    操作:
    1. 读取 nii
    2. 所有非零体素合并为 1
    3. 进行 3D 二值膨胀
    4. 保存为 原文件名_dilated.nii.gz
    '''

    nii_file = Path(nii_path)

    if not nii_file.exists() or not nii_file.is_file():
        raise FileNotFoundError(f"Not a valid nifti file: {nii_path}")

    if not (nii_file.suffix == ".nii" or nii_file.name.endswith(".nii.gz")):
        raise ValueError("Input must be .nii or .nii.gz file")

    # 读取 NIfTI
    img = nib.load(str(nii_file))
    data = img.get_fdata()
    affine = img.affine
    header = img.header

    # 合并所有非零体素为 1
    binary_mask = (data != 0)

    # 构造结构元素
    if structure_size % 2 == 0:
        raise ValueError("structure_size must be an odd number")

    structure = np.ones(
        (structure_size, structure_size, structure_size),
        dtype=bool
    )

    # 执行膨胀
    dilated_mask = binary_dilation(
        binary_mask,
        structure=structure,
        iterations=dilation_iterations
    )

    dilated_data = dilated_mask.astype(np.uint8)

    # 构造输出文件名
    base_name = nii_file.name
    if base_name.endswith(".nii.gz"):
        base_name = base_name[:-7]
    elif base_name.endswith(".nii"):
        base_name = base_name[:-4]

    out_path = nii_file.parent / f"{base_name}_dilated.nii.gz"

    # 保存
    new_img = nib.Nifti1Image(dilated_data, affine, header)
    nib.save(new_img, str(out_path))

    print(f"Saved dilated NIfTI to:")
    print(f"- {out_path}")

    return dilated_data

def nii_erosion(nii_path: str,
                erosion_iterations: int = 1,
                structure_size: int = 3):

    '''
    输入:
    - nii_path: 单个 .nii 或 .nii.gz 文件路径
    - erosion_iterations: 腐蚀次数
    - structure_size: 结构元素大小 (必须为奇数, 如 3,5,7)

    操作:
    1. 读取 nii
    2. 所有非零体素合并为 1
    3. 进行 3D 二值腐蚀
    4. 保存为 原文件名_eroded.nii.gz
    '''

    nii_file = Path(nii_path)

    if not nii_file.exists() or not nii_file.is_file():
        raise FileNotFoundError(f"Not a valid nifti file: {nii_path}")

    if not (nii_file.suffix == ".nii" or nii_file.name.endswith(".nii.gz")):
        raise ValueError("Input must be .nii or .nii.gz file")

    img = nib.load(str(nii_file))
    data = img.get_fdata()
    affine = img.affine
    header = img.header

    binary_mask = (data != 0)

    if structure_size % 2 == 0:
        raise ValueError("structure_size must be an odd number")

    structure = np.ones(
        (structure_size, structure_size, structure_size),
        dtype=bool
    )

    eroded_mask = binary_erosion(
        binary_mask,
        structure=structure,
        iterations=erosion_iterations
    )

    eroded_data = eroded_mask.astype(np.uint8)

    base_name = nii_file.name
    if base_name.endswith(".nii.gz"):
        base_name = base_name[:-7]
    elif base_name.endswith(".nii"):
        base_name = base_name[:-4]

    out_path = nii_file.parent / f"{base_name}_eroded.nii.gz"

    new_img = nib.Nifti1Image(eroded_data, affine, header)
    nib.save(new_img, str(out_path))

    print(f"Saved eroded NIfTI to: {out_path}")

    return eroded_data

def nii1_sub_nii2(nii1_path, nii2_path):

    '''
    输入:
    nii1_path: 第一个 nifti 文件路径 (.nii 或 .nii.gz)
    nii2_path: 第二个 nifti 文件路径 (.nii 或 .nii.gz)

    操作:
    1. 读取 nii1 和 nii2
    2. 将 nii1 中的非零体素减去 nii2 中的非零体素
       即: 保留 nii1 非零 且 nii2 为 0 的体素
    3. 保存为 nii1 原目录下的 nii1_sub_nii2.nii.gz
    '''

    nii1 = nib.load(nii1_path)
    nii2 = nib.load(nii2_path)

    data1 = nii1.get_fdata()
    data2 = nii2.get_fdata()

    if data1.shape != data2.shape:
        raise ValueError("两个 NIfTI 尺寸不一致，无法进行减法操作")

    mask1 = data1 != 0
    mask2 = data2 != 0

    result_mask = mask1 & (~mask2)

    result_data = np.zeros_like(data1)
    result_data[result_mask] = 1

    output_dir = os.path.dirname(nii1_path)
    output_path = os.path.join(output_dir, "nii1_sub_nii2.nii.gz")

    result_nii = nib.Nifti1Image(result_data.astype(np.uint8), nii1.affine, nii1.header)
    nib.save(result_nii, output_path)

    print(f"Saved: {output_path}")

if __name__ == "__main__":

    '''
    Command line usage example:
    /Users/tianye/venvs/py313/bin/python3.13 'Brain dilated.py' --brain_nii_path=./wmparc.nii.gz --export_individual=False --dilation_iterations=5 --structure_size=5
    '''

    parser = argparse.ArgumentParser(description="NIfTI2PLY and dilation operations for gyrus detection")

    parser.add_argument(
        "--brain_nii_path",
        type=str,
        required=True,
        help="Path to input .nii or .nii.gz file"
    )

    parser.add_argument(
        "--export_individual",
        type=lambda x: str(x).lower() == "true",
        default=False,
        help="Whether to export individual label PLY files (True/False)"
    )

    parser.add_argument(
        "--dilation_iterations",
        type=int,
        default=5,
        help="Number of dilation iterations"
    )

    parser.add_argument(
        "--structure_size",
        type=int,
        default=5,
        help="Structuring element size (must be odd)"
    )

    args = parser.parse_args()

    nii_path = args.brain_nii_path

    # 1) 先对原始 nii 输出 ply
    nii2ply(
        nii_path=nii_path,
        export_individual=args.export_individual
    )

    # 2) 进行膨胀
    dilated_data = nii_dilation(
        nii_path=nii_path,
        dilation_iterations=args.dilation_iterations,
        structure_size=args.structure_size
    )

    # 3) 对膨胀后的 nii 再输出 ply
    original_path = Path(nii_path)
    base_name = original_path.name
    if base_name.endswith(".nii.gz"):
        base_name = base_name[:-7]
    elif base_name.endswith(".nii"):
        base_name = base_name[:-4]

    dilated_path = original_path.parent / f"{base_name}_dilated.nii.gz"

    nii2ply(
        nii_path=str(dilated_path),
        export_individual=False
    )