# 脑沟脑回分割（Brain Gyrus Segmentation）

基于 MRI 脑区标注数据，通过 **NIfTI → PLY 网格转换 → Blender 布料收缩模拟** 的流水线，从大脑皮层三维模型中提取脑回（gyrus）表面网格。

## 工作原理

```
NIfTI (.nii.gz) ──→ 原始脑 PLY ＋ 膨胀脑 PLY ──→ Blender 布料收缩 ──→ 脑回 PLY
```

1. **体素 → 网格**：读取 FreeSurfer `wmparc` 标注的 NIfTI 文件，使用 Marching Cubes 将各脑区转为三维 PLY 网格；再对二值化掩膜做三维膨胀，生成膨胀包络。
2. **布料收缩模拟**：在 Blender 中将原始脑设为静态碰撞体，膨胀包络设为收缩布料，利用物理模拟将包络紧贴到脑表面。
3. **后处理**：Remesh（平滑）→ Solidify（实体化一薄壳）→ Boolean Intersect（与脑皮层表面求交）→ Subdivision 精修，导出最终脑回网格。

## 效果展示

### 原始大脑网格

![原始大脑表面](1%20大脑.png)

### 大脑 + 脑回叠加

将提取出的脑回（红色线框）叠加在原始大脑表面：

![大脑与脑回叠加](2%20大脑+脑回.png)

### 膨胀包络（初始布料）

对大脑体积膨胀后生成的包络网格，作为布料收缩模拟的起点：

![初始布料包络](3%20初始的布料.png)

### 收缩后的布料

经 Blender 布料物理模拟后，包络紧贴至大脑皮质表面：

![收紧的布料](4%20收紧的布料.png)

### 布料收缩动画

从膨胀包络到贴合脑表面的完整物理模拟过程：

[▶ 点击观看布料收缩模拟动画](布料解算动画.mp4)

## 文件说明

### 核心脚本

| 文件                               | 用途                                               | 运行环境                            |
| ---------------------------------- | -------------------------------------------------- | ----------------------------------- |
| `Brain dilated.py`               | NIfTI 转 PLY、三维膨胀/腐蚀、体积减法              | 系统 Python 3                       |
| `blender_gyrus_pipeline.py`      | Blender 管线核心库（导入、布料模拟、后处理、导出） | Blender Python                      |
| `Blender scripting.py`           | Blender 命令行入口脚本                             | Blender (`--background --python`) |
| `Blender scripting - IDE执行.py` | IDE 内调试用入口（硬编码路径）                     | Blender Python (IDE)                |

### 输入 / 输出示例

- `wmparc.nii.gz` — 原始 FreeSurfer 脑区分割（输入）
- `wmparc_all.ply` — 全脑 PLY 网格（中间产物）
- `wmparc_dilated.nii.gz`、`wmparc_dilated_all.ply` — 膨胀后网格（中间产物）
- `gyrus.ply` — 最终脑回网格（输出）
- `Individual PLYs/` — 各脑区独立 PLY（可选输出）
- `PNG 1~50/` — 模拟过程帧截图
- `*.blend` / `*.blend1` — Blender 工程文件

## 依赖

### Python（`Brain dilated.py`）

- Python ≥ 3.9
- `numpy`
- `nibabel`
- `scikit-image`
- `scipy`

```bash
pip install numpy nibabel scikit-image scipy
```

### Blender（`blender_gyrus_pipeline.py` / `Blender scripting.py`）

- Blender ≥ 3.6（推荐 4.x 或 5.x）
- 无需额外 Python 包，使用 Blender 内置 `bpy`

## 使用方法

### 第一步：NIfTI → PLY + 膨胀

```bash
python "Brain dilated.py" \
    --brain_nii_path=./wmparc.nii.gz \
    --export_individual=False \
    --dilation_iterations=5 \
    --structure_size=5
```

生成 `wmparc_all.ply` 和 `wmparc_dilated_all.ply`。

### 第二步：Blender 收缩模拟 + 导出脑回

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
    --background \
    --python "Blender scripting.py" \
    -- \
    --brain_ply_path=./wmparc_all.ply \
    --end_frame=150
```

生成最终 `gyrus.ply`。

### 一键执行上述两个步骤

```bash
python "Brain dilated.py" \
    --brain_nii_path=wmparc.nii.gz \
    --export_individual=False \
    --dilation_iterations=5 \
    --structure_size=5 \
&& \
/Applications/Blender.app/Contents/MacOS/Blender \
    --background \
    --python "Blender scripting.py" \
    -- \
    --brain_ply_path=wmparc_all.ply \
    --end_frame=150
```

## 可调参数

| 参数                      | 默认值 | 说明                                                   |
| ------------------------- | ------ | ------------------------------------------------------ |
| `--dilation_iterations` | 5      | 膨胀迭代次数，越大膨胀越多；不建议修改，此数值效果最佳 |
| `--structure_size`      | 5      | 膨胀结构元素尺寸（奇数）；不建议修改，此数值效果最佳   |
| `--end_frame`           | 150    | 布料模拟结束帧，帧数越大越接近最终平衡状态             |
| `shrinking_factor`      | 0.4    | 布料收缩系数                                           |
| `pressure`              | -10.0  | 负压使布料向内收缩                                     |

## 原理参考

- FreeSurfer `wmparc` 分割
- Blender Cloth Simulation：基于弹簧-质点模型的物理模拟

## 许可

MIT License
