# -*- coding: utf-8 -*-
"""
Búsqueda por FOTO en el servidor — reusa la tecnología del verificador de
precios: el índice de embeddings publicado en /indice/ (CLIP o DINOv2, int8)
se compara contra la foto que manda el cliente. Devuelve los SKUs más
parecidos con su puntaje de similitud.

Calibración con el índice real (24.765 fotos, CLIP ViT-B/16):
  - pares al azar: ~0.60  ·  mismo producto: ~0.92+
  - umbrales: ALTA >= 0.88, MEDIA >= 0.80, menos = se descarta.

Todo es tolerante a fallos: si el índice o el modelo no cargan, devuelve []
y el flujo sigue solo con la descripción de visión (Claude).
"""

import asyncio
import io
import json
import os
import time

import httpx

INDICE_URL = (os.getenv("INDICE_IMG_URL",
                        "https://precios.shoppingasia.com.py/indice")
              .rstrip("/"))
ACTIVO = (os.getenv("FOTO_MATCH", "1").strip().lower()
          not in ("0", "no", "off", "false"))

# Modelos soportados (el que diga img_meta.json). Se baja el ONNX cuantizado.
_MODELOS = {
    "Xenova/clip-vit-base-patch16": {
        "onnx": ("https://huggingface.co/Xenova/clip-vit-base-patch16/"
                 "resolve/main/onnx/vision_model_quantized.onnx"),
        "tipo": "clip", "lado": 224,
        "mean": (0.48145466, 0.4578275, 0.40821073),
        "std": (0.26862954, 0.26130258, 0.27577711),
    },
    "Xenova/dinov2-small": {
        "onnx": ("https://huggingface.co/Xenova/dinov2-small/"
                 "resolve/main/onnx/model_quantized.onnx"),
        "tipo": "dino", "lado": 224,
        "mean": (0.485, 0.456, 0.406),
        "std": (0.229, 0.224, 0.225),
    },
}

_st = {"listo": False, "fallo_ts": 0.0, "skus": None, "V": None,
       "cfg": None, "sesion": None, "ts_indice": 0.0}
_lock = asyncio.Lock()


async def _preparar():
    """Carga índice publicado + modelo ONNX (una vez; reintenta cada 30 min)."""
    if _st["listo"] and time.time() - _st["ts_indice"] < 6 * 3600:
        return True
    if time.time() - _st["fallo_ts"] < 1800:
        return _st["listo"]
    async with _lock:
        if _st["listo"] and time.time() - _st["ts_indice"] < 6 * 3600:
            return True
        try:
            import numpy as np
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as cli:
                meta = (await cli.get(f"{INDICE_URL}/img_meta.json")).json()
                modelo = meta.get("modelo", "")
                cfg = _MODELOS.get(modelo)
                if not cfg:
                    raise RuntimeError(f"modelo del indice no soportado: {modelo}")
                skus = (await cli.get(f"{INDICE_URL}/img_skus.json")).json()
                rb = await cli.get(f"{INDICE_URL}/img_vectores.bin")
                V = (np.frombuffer(rb.content, dtype=np.int8)
                     .reshape(len(skus), int(meta["dim"])).astype(np.float32) / 127.0)
                V /= (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
                # modelo ONNX (se guarda en /tmp; sobrevive reinicios, no deploys)
                ruta = f"/tmp/vision_{abs(hash(cfg['onnx'])) % 99999}.onnx"
                if not os.path.exists(ruta) or os.path.getsize(ruta) < 1e6:
                    rm = await cli.get(cfg["onnx"])
                    rm.raise_for_status()
                    with open(ruta, "wb") as f:
                        f.write(rm.content)
            import onnxruntime as ort
            sesion = ort.InferenceSession(ruta, providers=["CPUExecutionProvider"])
            _st.update(listo=True, skus=skus, V=V, cfg=cfg, sesion=sesion,
                       ts_indice=time.time())
            print(f"[IMG] indice de fotos listo: {len(skus)} vectores, "
                  f"modelo {modelo}", flush=True)
            return True
        except Exception as e:
            _st["fallo_ts"] = time.time()
            print(f"[IMG] no se pudo preparar la busqueda por foto: {e}", flush=True)
            return False


def _embed(img_bytes: bytes):
    """Embedding de la foto del cliente con el MISMO preproceso del índice."""
    import numpy as np
    from PIL import Image
    cfg = _st["cfg"]
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    # resize lado corto -> lado, luego center-crop lado x lado (como CLIP/DINO)
    lado = cfg["lado"]
    w, h = im.size
    esc = lado / min(w, h)
    im = im.resize((max(lado, round(w * esc)), max(lado, round(h * esc))),
                   Image.BICUBIC)
    w, h = im.size
    izq, arr = (w - lado) // 2, (h - lado) // 2
    im = im.crop((izq, arr, izq + lado, arr + lado))
    x = np.asarray(im).astype(np.float32) / 255.0
    x = (x - np.array(cfg["mean"], dtype=np.float32)) / np.array(cfg["std"], dtype=np.float32)
    x = x.transpose(2, 0, 1)[None, ...]          # 1x3xHxW
    ses = _st["sesion"]
    nombre = ses.get_inputs()[0].name
    out = ses.run(None, {nombre: x})
    if cfg["tipo"] == "clip":
        emb = out[0][0]                          # image_embeds
    else:
        emb = out[0][0][0]                       # last_hidden_state CLS
    emb = emb.astype(np.float32)
    emb /= (np.linalg.norm(emb) + 1e-9)
    return emb


async def buscar_por_imagen(img_bytes: bytes, k: int = 3):
    """[(sku, similitud)] de los k productos más parecidos, o []."""
    if not (ACTIVO and img_bytes):
        return []
    if not await _preparar():
        return []
    try:
        import numpy as np
        q = await asyncio.to_thread(_embed, img_bytes)
        scores = _st["V"] @ q
        orden = np.argsort(-scores)
        vistos, res = set(), []
        for i in orden:
            sku = str(_st["skus"][int(i)])
            if sku in vistos:
                continue
            vistos.add(sku)
            res.append((sku, float(scores[int(i)])))
            if len(res) >= k:
                break
        print(f"[IMG] match: {[(s, round(p, 3)) for s, p in res]}", flush=True)
        return res
    except Exception as e:
        print(f"[IMG] error en match: {e}", flush=True)
        return []
