import numpy as np


def _build_uniform_table() -> np.ndarray:
    """Mapea los 256 codigos LBP de 8 bits a sus 59 bins uniformes
    (58 patrones uniformes + 1 para los no uniformes)."""
    table = np.full(256, 58, dtype=np.uint8)
    idx = 0
    for value in range(256):
        bits = [(value >> k) & 1 for k in range(8)]
        transitions = sum(bits[k] != bits[(k + 1) % 8] for k in range(8))
        if transitions <= 2:
            table[value] = idx
            idx += 1
    return table


_UNIFORM_TABLE = _build_uniform_table()


def _neighbors(gray: np.ndarray, radius: float) -> np.ndarray:
    """Devuelve (8, rows, cols) con cada vecino a la distancia dada
    (interpolacion bilineal cuando el radio no es entero)."""
    rows, cols = gray.shape
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    offsets = [
        (0, radius),
        (radius * np.cos(np.pi / 4), radius * np.sin(np.pi / 4)),
        (radius, 0),
        (radius * np.cos(np.pi / 4), -radius * np.sin(np.pi / 4)),
        (0, -radius),
        (-radius * np.cos(np.pi / 4), -radius * np.sin(np.pi / 4)),
        (-radius, 0),
        (-radius * np.cos(np.pi / 4), radius * np.sin(np.pi / 4)),
    ]
    out = []
    for dy, dx in offsets:
        yc, xc = y + dy, x + dx
        y0 = np.clip(np.floor(yc).astype(int), 0, rows - 1)
        x0 = np.clip(np.floor(xc).astype(int), 0, cols - 1)
        y1 = np.clip(y0 + 1, 0, rows - 1)
        x1 = np.clip(x0 + 1, 0, cols - 1)
        fy = yc - y0
        fx = xc - x0
        top = gray[y0, x0] * (1 - fx) + gray[y0, x1] * fx
        bottom = gray[y1, x0] * (1 - fx) + gray[y1, x1] * fx
        out.append(top * (1 - fy) + bottom * fy)
    return np.stack(out)


def lbp_codes(gray: np.ndarray, radius: float = 1.0) -> np.ndarray:
    """Codigo LBP por pixel comparando con sus 8 vecinos a la distancia dada."""
    neighbors = _neighbors(gray, radius)
    code = np.zeros(gray.shape, dtype=np.uint16)
    for bit in range(8):
        code |= (neighbors[bit] >= gray).astype(np.uint16) << bit
    return code


def extract_lbph(
    gray: np.ndarray,
    blocks: tuple[int, int] = (8, 8),
    radii: tuple[float, ...] = (1.0, 2.0),
) -> np.ndarray:
    """Describe una cara con histogramas LBP uniformes por bloque, concatenando
    varias escalas (radios). El descriptor final se normaliza L2."""
    rows, cols = gray.shape
    bh, bw = rows // blocks[0], cols // blocks[1]
    features = []
    for radius in radii:
        codes = _UNIFORM_TABLE[lbp_codes(gray, radius)]
        for i in range(blocks[0]):
            for j in range(blocks[1]):
                cell = codes[i * bh : (i + 1) * bh, j * bw : (j + 1) * bw]
                hist = np.bincount(cell.ravel(), minlength=59).astype(np.float64)
                norm = np.linalg.norm(hist)
                features.append(hist / norm if norm > 0 else hist)
    vec = np.concatenate(features)
    norm = np.linalg.norm(vec)
    return (vec / norm).astype(np.float32) if norm > 0 else vec.astype(np.float32)
