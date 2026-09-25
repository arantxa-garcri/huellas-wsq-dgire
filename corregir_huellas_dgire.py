#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Proyecto: procesamiento masivo de huellas WSQ para DGIRE (V2)
# Archivo: corregir_huellas_dgire.py
# Autoría: Arantxa GC
# Copyright (C) 2026 Arantxa GC
# Asistencia de desarrollo y documentación: ChatGPT / Codex (OpenAI)
# Fecha de creación: 2026-09-24
# SPDX-License-Identifier: GPL-3.0-only
#
# Este programa es software libre: puede redistribuirse y modificarse
# bajo los términos de la Licencia Pública General de GNU, versión 3,
# publicada por la Free Software Foundation.
#
# Se distribuye con la intención de que resulte útil, pero SIN NINGUNA
# GARANTÍA; ni siquiera la garantía implícita de COMERCIABILIDAD o
# IDONEIDAD PARA UN PROPÓSITO PARTICULAR.
#
# Consulte el archivo LICENSE para conocer los términos completos.
# Si no recibió una copia de la licencia, puede consultarla en:
# https://www.gnu.org/licenses/gpl-3.0.html
#
# Las dependencias conservan sus respectivas licencias.
#
# Objetivo: localizar la huella, recortar sin escalar y generar un WSQ
# que supere los controles técnicos implementados.
# Uso: python3 corregir_huellas_dgire.py "/ruta/a/1010"
# Requiere: Pillow, NumPy y python-wsq con los parches del README.md.
#
# Respaldar los originales y las salidas V2 antes de cada ejecución.
# No modificar originales ni escalar las huellas para forzar su aceptación.
# La validación biométrica final debe hacerse con VeriFinger.
# ============================================================

from pathlib import Path
from PIL import Image
import wsq
import _wsq
import numpy as np

import csv
import sys
import subprocess
import json
from collections import defaultdict


# ============================================================
# CONFIGURACIÓN DGIRE
# ============================================================
# Parámetros de salida y tolerancias internas usados por todo el procesamiento.
# Cambiarlos altera los criterios de aceptación; revisar el instructivo aplicable.

CARPETA_SALIDA = "HUELLAS_DIGITALES_CORREGIDAS_V2"

PREFIJO_CORREGIDAS = (
    "HUELLAS_DIGITALES_CORREGIDAS"
)

ANCHO_FINAL = 512
ALTO_FINAL = 512

PROFUNDIDAD_BITS = 8
PPI_REQUERIDO = 500


# ------------------------------------------------------------
# Tamaño
#
# Usamos un intervalo ligeramente más estricto para que
# cumpla tanto si "KB" se interpreta como 1000 bytes como
# si se interpreta como 1024 bytes.
# ------------------------------------------------------------

MIN_BYTES = 15 * 1024
MAX_BYTES = 40000


# ------------------------------------------------------------
# Compresión
#
# 512 × 512 × 8 bits:
# 262144 bytes sin comprimir.
#
# Para 15:1:
#
# 262144 / 15 ≈ 17476 bytes.
# ------------------------------------------------------------

RAW_BYTES = (
    ANCHO_FINAL
    * ALTO_FINAL
)

TARGET_RATIO = 15.0

TARGET_BYTES = int(
    round(
        RAW_BYTES
        / TARGET_RATIO
    )
)


# NIST utiliza 0.75 como referencia aproximada
# para 15:1.

BITRATE_REFERENCIA = 0.75

BITRATE_MIN = 0.35
BITRATE_MAX = 2.25

ITERACIONES_BITRATE = 11


# Relación efectiva aceptable alrededor de 15:1.

RATIO_MIN = 13.5
RATIO_MAX = 16.5


# Máximo porcentaje de región detectada de huella
# permitido fuera del crop.

MAX_PIXELES_FUERA_PCT = 1.5


# ============================================================
# FUNCIONES GENERALES
# ============================================================

def es_carpeta_corregida(ruta):

    # Reconoce carpetas de resultados por su prefijo en cualquier parte de la ruta.
    # Evita volver a procesar tanto la primera revisión como las salidas V2.

    return any(
        parte.startswith(
            PREFIJO_CORREGIDAS
        )
        for parte in ruta.parts
    )


# ============================================================
# OTSU
# ============================================================

def calcular_otsu(arr):

    # Calcula un umbral global a partir del histograma de intensidades.
    # Elige la separación que maximiza la diferencia entre dos clases de píxeles;
    # no identifica crestas ni minutias biométricas.

    hist = np.bincount(
        arr.ravel(),
        minlength=256
    ).astype(np.float64)

    total = arr.size

    suma_total = np.dot(
        np.arange(256),
        hist
    )

    suma_fondo = 0.0
    peso_fondo = 0.0

    max_varianza = -1.0
    mejor_umbral = 127

    for t in range(256):

        peso_fondo += hist[t]

        if peso_fondo == 0:
            continue

        peso_frente = (
            total
            - peso_fondo
        )

        if peso_frente == 0:
            break

        suma_fondo += (
            t * hist[t]
        )

        media_fondo = (
            suma_fondo
            / peso_fondo
        )

        media_frente = (
            (
                suma_total
                - suma_fondo
            )
            / peso_frente
        )

        varianza = (
            peso_fondo
            * peso_frente
            * (
                media_fondo
                - media_frente
            ) ** 2
        )

        if varianza > max_varianza:

            max_varianza = varianza
            mejor_umbral = t

    return int(
        mejor_umbral
    )


# ============================================================
# DETECTAR REGIÓN DE HUELLA
# ============================================================

def construir_mascara_huella(
    imagen
):

    # Recibe una imagen en escala de grises y estima qué píxeles son huella.
    # Combina el fondo de los bordes con Otsu y filtra ruido por filas y columnas.
    # Devuelve el raster, la máscara booleana, el fondo estimado y el umbral.
    # La máscara solo guía el recorte: no se aplica como filtro a la imagen final.

    arr = np.asarray(
        imagen,
        dtype=np.uint8
    )

    alto, ancho = arr.shape


    # --------------------------------------------------------
    # Estimar fondo usando los bordes
    # --------------------------------------------------------

    borde = max(
        8,
        min(alto, ancho) // 60
    )

    muestras = np.concatenate([

        arr[:borde, :].ravel(),

        arr[-borde:, :].ravel(),

        arr[:, :borde].ravel(),

        arr[:, -borde:].ravel()

    ])


    fondo = float(
        np.median(muestras)
    )


    otsu = calcular_otsu(
        arr
    )


    umbral = int(
        np.clip(

            min(
                fondo - 8,
                otsu + 20
            ),

            70,
            245
        )
    )


    mascara = (
        arr < umbral
    )


    # --------------------------------------------------------
    # Eliminar ruido disperso
    #
    # Un píxel se considera parte útil únicamente si su fila
    # y columna contienen una cantidad mínima de región oscura.
    # --------------------------------------------------------

    conteo_filas = (
        mascara.sum(axis=1)
    )

    conteo_columnas = (
        mascara.sum(axis=0)
    )


    min_fila = max(
        6,
        int(
            round(
                ancho * 0.012
            )
        )
    )


    min_columna = max(
        6,
        int(
            round(
                alto * 0.012
            )
        )
    )


    filas_validas = (
        conteo_filas
        >= min_fila
    )


    columnas_validas = (
        conteo_columnas
        >= min_columna
    )


    mascara_filtrada = (

        mascara

        & filas_validas[:, None]

        & columnas_validas[None, :]

    )


    # Si el filtro eliminó demasiado,
    # usar la máscara original.

    if (
        mascara_filtrada.sum()
        <
        max(
            500,
            int(
                mascara.sum()
                * 0.55
            )
        )
    ):

        mascara_filtrada = (
            mascara
        )


    if (
        mascara_filtrada.sum()
        < 500
    ):

        raise ValueError(
            "No fue posible detectar "
            "suficiente región de huella."
        )


    return (
        arr,
        mascara_filtrada,
        fondo,
        umbral
    )


# ============================================================
# LIMITES ROBUSTOS
# ============================================================

def limites_robustos(
    mascara
):

    # Obtiene límites y centro aproximados usando percentiles de la máscara.
    # Descarta los extremos al estimar el rectángulo para reducir el efecto del ruido.
    # Devuelve coordenadas y dimensiones; no garantiza que todas las crestas quepan.

    ys, xs = np.nonzero(
        mascara
    )


    if len(xs) == 0:

        raise ValueError(
            "Máscara de huella vacía."
        )


    # Ignoramos el 1% extremo de píxeles
    # para que una mancha aislada no expanda
    # todo el bounding box.

    x_min = int(
        np.floor(
            np.quantile(
                xs,
                0.01
            )
        )
    )


    x_max = int(
        np.ceil(
            np.quantile(
                xs,
                0.99
            )
        )
    )


    y_min = int(
        np.floor(
            np.quantile(
                ys,
                0.01
            )
        )
    )


    y_max = int(
        np.ceil(
            np.quantile(
                ys,
                0.99
            )
        )
    )


    centro_x = (
        x_min + x_max
    ) / 2.0


    centro_y = (
        y_min + y_max
    ) / 2.0


    return {

        "x_min": x_min,
        "x_max": x_max,

        "y_min": y_min,
        "y_max": y_max,

        "centro_x":
            centro_x,

        "centro_y":
            centro_y,

        "ancho_huella":
            x_max
            - x_min
            + 1,

        "alto_huella":
            y_max
            - y_min
            + 1
    }


# ============================================================
# ENCONTRAR EL MEJOR CROP 512 x 512
# ============================================================

def mejor_ventana_512(
    mascara,
    centro_x,
    centro_y
):

    # Evalúa recortes de 512 × 512 mediante una imagen de sumas acumuladas.
    # Entre ventanas con conservación casi máxima, prefiere la más centrada.
    # Devuelve las coordenadas y el porcentaje de máscara que quedaría fuera.
    # Una entrada menor que la ventana genera una excepción; no se amplía.

    alto, ancho = (
        mascara.shape
    )


    if (
        ancho < ANCHO_FINAL
        or
        alto < ALTO_FINAL
    ):

        raise ValueError(
            "La imagen original es menor "
            "que 512x512."
        )


    m = mascara.astype(
        np.int32
    )


    # --------------------------------------------------------
    # Integral image
    #
    # Permite calcular cuántos píxeles de huella
    # contiene cada posible ventana 512x512.
    # --------------------------------------------------------

    integral = np.pad(

        m.cumsum(
            axis=0
        ).cumsum(
            axis=1
        ),

        (
            (1, 0),
            (1, 0)
        ),

        mode="constant"
    )


    h = ALTO_FINAL
    w = ANCHO_FINAL


    sumas = (

        integral[h:, w:]

        - integral[:-h, w:]

        - integral[h:, :-w]

        + integral[:-h, :-w]

    )


    max_suma = int(
        sumas.max()
    )


    total_huella = int(
        m.sum()
    )


    # Varias ventanas pueden conservar prácticamente
    # toda la huella. Entre ellas preferimos aquella
    # cuyo centro queda más cerca del centro robusto.

    tolerancia = max(

        1,

        int(
            round(
                max_suma
                * 0.0015
            )
        )
    )


    candidatos = np.argwhere(

        sumas
        >=
        (
            max_suma
            - tolerancia
        )

    )


    centros_x = (

        candidatos[:, 1]

        + ANCHO_FINAL / 2.0
    )


    centros_y = (

        candidatos[:, 0]

        + ALTO_FINAL / 2.0
    )


    dist2 = (

        (
            centros_x
            - centro_x
        ) ** 2

        +

        (
            centros_y
            - centro_y
        ) ** 2

    )


    elegido = candidatos[
        int(
            np.argmin(dist2)
        )
    ]


    arriba = int(
        elegido[0]
    )


    izquierda = int(
        elegido[1]
    )


    dentro = int(
        sumas[
            arriba,
            izquierda
        ]
    )


    fuera_pct = (

        (
            total_huella
            - dentro
        )

        / total_huella

        * 100.0

    )


    return {

        "crop_left":
            izquierda,

        "crop_top":
            arriba,

        "crop_right":
            izquierda
            + ANCHO_FINAL,

        "crop_bottom":
            arriba
            + ALTO_FINAL,

        "pixeles_huella_total":
            total_huella,

        "pixeles_huella_dentro":
            dentro,

        "pixeles_huella_fuera_pct":
            fuera_pct
    }


# ============================================================
# CODIFICAR WSQ CON BITRATE VARIABLE
# ============================================================

def codificar_wsq(
    imagen,
    bitrate
):

    # Codifica los píxeles del recorte directamente en WSQ con el bitrate indicado.
    # La extensión C recibe alto y ancho en ese orden y debe estar parcheada
    # para respetar el bitrate. No introduce escalado ni un formato JPEG intermedio.

    if imagen.mode != "L":

        imagen = (
            imagen.convert("L")
        )


    raw = imagen.tobytes()


    return _wsq.compress(

        raw,

        imagen.height,

        imagen.width,

        float(bitrate)
    )


# ============================================================
# VALIDAR WSQ
# ============================================================

def validar_wsq_bytes(
    data
):

    # Decodifica un WSQ y comprueba dimensiones, PPI y longitud del raster.
    # La profundidad informada corresponde al flujo de 8 bits configurado.
    # Esta comprobación técnica no evalúa calidad biométrica ni identidad.

    raw, ancho, alto, ppi = (
        _wsq.decompress(data)
    )


    if (
        ancho != 512
        or
        alto != 512
    ):

        raise ValueError(
            f"WSQ final mide "
            f"{ancho}x{alto}."
        )


    if ppi != PPI_REQUERIDO:

        raise ValueError(
            f"WSQ final reporta "
            f"{ppi} PPI."
        )


    if len(raw) != RAW_BYTES:

        raise ValueError(
            "Raster decodificado tiene "
            "un tamaño inesperado."
        )


    return {

        "ancho": ancho,

        "alto": alto,

        "ppi": ppi,

        "depth":
            PROFUNDIDAD_BITS
    }


# ============================================================
# LEER BITRATE DEL NISTCOM
# ============================================================

def extraer_bitrate_nistcom(
    data
):

    # Busca el parámetro WSQ_BITRATE en los metadatos del archivo.
    # Devuelve un número si puede leerlo y None si está ausente o no es interpretable.
    # Es una lectura orientativa, no un analizador completo del contenedor WSQ.

    marca = b"WSQ_BITRATE"

    pos = data.find(
        marca
    )


    if pos < 0:
        return None


    fragmento = (
        data[
            pos:
            pos + 80
        ]
    )


    try:

        texto = (
            fragmento.decode(
                "ascii",
                errors="ignore"
            )
        )


        partes = (
            texto
            .replace(
                "\r",
                "\n"
            )
            .split()
        )


        for i, parte in enumerate(
            partes
        ):

            if (
                parte
                ==
                "WSQ_BITRATE"

                and

                i + 1
                < len(partes)
            ):

                return float(
                    partes[i + 1]
                )

    except Exception:
        pass


    return None


# ============================================================
# BUSCAR LA COMPRESIÓN QUE CUMPLA DGIRE
# ============================================================

def buscar_codificacion_dgire(
    imagen
):

    # Prueba el bitrate de referencia y, si hace falta, busca otros valores.
    # Solo admite candidatos dentro de los límites de tamaño y relación efectiva.
    # Selecciona el más cercano al tamaño objetivo; falla si ninguno cumple.
    # La tolerancia alrededor de 15:1 es propia del programa, no una certificación.

    candidatos = {}


    def probar(
        bitrate
    ):

        # Memoriza cada codificación por bitrate para evitar repetir el mismo trabajo.
        # Calcula tamaño y relación efectiva a partir de los bytes reales del WSQ.

        clave = round(
            float(bitrate),
            6
        )


        if clave not in candidatos:

            data = codificar_wsq(
                imagen,
                clave
            )


            size = len(data)


            candidatos[
                clave
            ] = {

                "bitrate":
                    clave,

                "data":
                    data,

                "bytes":
                    size,

                "kb":
                    size / 1024.0,

                "ratio_efectivo":
                    RAW_BYTES / size
            }


        return candidatos[
            clave
        ]


    # --------------------------------------------------------
    # Primero probar el valor NIST de referencia
    # --------------------------------------------------------

    referencia = probar(
        BITRATE_REFERENCIA
    )


    if (

        MIN_BYTES
        <= referencia["bytes"]
        <= MAX_BYTES

        and

        RATIO_MIN
        <= referencia[
            "ratio_efectivo"
        ]
        <= RATIO_MAX

    ):

        return referencia


    # --------------------------------------------------------
    # Buscar automáticamente un bitrate apropiado
    # --------------------------------------------------------

    bajo = BITRATE_MIN
    alto = BITRATE_MAX


    probar(bajo)
    probar(alto)


    for _ in range(
        ITERACIONES_BITRATE
    ):

        medio = (
            bajo + alto
        ) / 2.0


        resultado = probar(
            medio
        )


        if (
            resultado["bytes"]
            <
            TARGET_BYTES
        ):

            bajo = medio

        else:

            alto = medio


    # --------------------------------------------------------
    # Solo aceptar candidatos que cumplen AMBAS condiciones
    # --------------------------------------------------------

    validos = [

        c

        for c in candidatos.values()

        if (

            MIN_BYTES
            <= c["bytes"]
            <= MAX_BYTES

            and

            RATIO_MIN
            <= c["ratio_efectivo"]
            <= RATIO_MAX

        )

    ]


    if not validos:

        menor = min(

            candidatos.values(),

            key=lambda c:
            c["bytes"]

        )


        mayor = max(

            candidatos.values(),

            key=lambda c:
            c["bytes"]

        )


        raise ValueError(

            "No se encontró una codificación "
            "que cumpla simultáneamente "
            "15-40 KB y una relación cercana "
            "a 15:1. "

            f"Rango probado: "
            f"{menor['kb']:.2f}-"
            f"{mayor['kb']:.2f} KB."

        )


    mejor = min(

        validos,

        key=lambda c: (

            abs(
                c["bytes"]
                - TARGET_BYTES
            ),

            abs(
                c["bitrate"]
                - BITRATE_REFERENCIA
            )
        )
    )


    return mejor


# ============================================================
# PROCESAR UN ARCHIVO
# ============================================================

def procesar_un_archivo(
    origen,
    destino
):

    # Procesa una entrada completa: detección, recorte, compresión y validación.
    # Elimina primero cualquier salida previa del mismo destino: respaldar V2
    # antes de repetir el lote. El original se abre para lectura y no se reemplaza.
    # Devuelve las mediciones para el reporte solo si todas las etapas terminan.
    # Una excepción posterior a escribir puede dejar un archivo que debe revisarse.

    origen = Path(
        origen
    )


    destino = Path(
        destino
    )


    # Si existe un resultado V2 anterior,
    # no permitir que sobreviva si esta nueva
    # ejecución falla.

    if destino.exists():

        destino.unlink()


    # --------------------------------------------------------
    # Abrir WSQ original
    # --------------------------------------------------------

    with Image.open(
        origen
    ) as original:

        original.load()

        imagen = (
            original.convert("L")
        )


    ancho_original = (
        imagen.width
    )


    alto_original = (
        imagen.height
    )


    # --------------------------------------------------------
    # Detectar huella
    # --------------------------------------------------------

    (
        arr,
        mascara,
        fondo,
        umbral
    ) = construir_mascara_huella(
        imagen
    )


    region = limites_robustos(
        mascara
    )


    # --------------------------------------------------------
    # Encontrar mejor ventana 512x512
    # --------------------------------------------------------

    ventana = mejor_ventana_512(

        mascara,

        region["centro_x"],

        region["centro_y"]

    )


    fuera_pct = (
        ventana[
            "pixeles_huella_fuera_pct"
        ]
    )


    if (
        fuera_pct
        >
        MAX_PIXELES_FUERA_PCT
    ):

        raise ValueError(

            "El mejor recorte 512x512 "
            "dejaría fuera "

            f"{fuera_pct:.2f}% "

            "de la región detectada como huella. "
            "Se requiere revisión visual."

        )


    # --------------------------------------------------------
    # Recortar SIN resize
    # --------------------------------------------------------

    recorte = imagen.crop(

        (

            ventana["crop_left"],

            ventana["crop_top"],

            ventana["crop_right"],

            ventana["crop_bottom"]

        )

    )


    if (
        recorte.size
        !=
        (
            ANCHO_FINAL,
            ALTO_FINAL
        )
    ):

        raise ValueError(

            "El recorte no resultó "
            "512x512."

        )


    # --------------------------------------------------------
    # Cobertura orientativa
    # --------------------------------------------------------

    bbox_area_pct = (

        region["ancho_huella"]

        * region["alto_huella"]

        / (
            ANCHO_FINAL
            * ALTO_FINAL
        )

        * 100.0

    )


    # --------------------------------------------------------
    # Buscar codificación que cumpla tamaño + ~15:1
    # --------------------------------------------------------

    codificacion = (
        buscar_codificacion_dgire(
            recorte
        )
    )


    # --------------------------------------------------------
    # Validar archivo en memoria
    # --------------------------------------------------------

    validacion = (
        validar_wsq_bytes(
            codificacion["data"]
        )
    )


    bitrate_nistcom = (
        extraer_bitrate_nistcom(
            codificacion["data"]
        )
    )


    bytes_final = (
        codificacion["bytes"]
    )


    ratio_efectivo = (
        codificacion[
            "ratio_efectivo"
        ]
    )


    # --------------------------------------------------------
    # Condiciones obligatorias
    # --------------------------------------------------------

    if not (

        MIN_BYTES
        <= bytes_final
        <= MAX_BYTES

    ):

        raise ValueError(

            "El tamaño final quedó "
            "fuera del intervalo DGIRE."

        )


    if not (

        RATIO_MIN
        <= ratio_efectivo
        <= RATIO_MAX

    ):

        raise ValueError(

            "La relación efectiva quedó "
            "fuera de la tolerancia "
            "alrededor de 15:1."

        )


    # --------------------------------------------------------
    # Solo ahora escribir archivo
    # --------------------------------------------------------

    destino.parent.mkdir(

        parents=True,

        exist_ok=True
    )


    destino.write_bytes(

        codificacion["data"]

    )


    # --------------------------------------------------------
    # Segunda validación desde el disco
    # --------------------------------------------------------

    data_final = (
        destino.read_bytes()
    )


    validar_wsq_bytes(
        data_final
    )


    return {

        "estado":
            "OK_DGIRE_TECNICO",

        "ancho_original":
            ancho_original,

        "alto_original":
            alto_original,

        "ancho_final":
            validacion["ancho"],

        "alto_final":
            validacion["alto"],

        "depth_final":
            validacion["depth"],

        "ppi_final":
            validacion["ppi"],

        "x_min":
            region["x_min"],

        "x_max":
            region["x_max"],

        "y_min":
            region["y_min"],

        "y_max":
            region["y_max"],

        "centro_x":
            round(
                region["centro_x"],
                2
            ),

        "centro_y":
            round(
                region["centro_y"],
                2
            ),

        "crop_left":
            ventana["crop_left"],

        "crop_top":
            ventana["crop_top"],

        "ancho_huella":
            region["ancho_huella"],

        "alto_huella":
            region["alto_huella"],

        "bbox_area_pct":
            round(
                bbox_area_pct,
                2
            ),

        "pixeles_fuera_pct":
            round(
                fuera_pct,
                4
            ),

        "fondo_estimado":
            round(
                fondo,
                2
            ),

        "umbral":
            umbral,

        "bitrate_usado":
            round(
                codificacion[
                    "bitrate"
                ],
                6
            ),

        "bitrate_nistcom":

            (
                round(
                    bitrate_nistcom,
                    6
                )

                if (
                    bitrate_nistcom
                    is not None
                )

                else ""
            ),

        "bytes_final":
            bytes_final,

        "kb_final":
            round(
                bytes_final
                / 1024.0,
                2
            ),

        "ratio_efectivo":
            round(
                ratio_efectivo,
                3
            ),

        "observaciones":

            (
                "WSQ 512x512, 8 bits, "
                "500 PPI, tamaño correcto "
                "y relación cercana a 15:1. "
                "Recorte centrado sin resize. "
                "La calidad biométrica final "
                "debe validarse con VeriFinger."
            )
    }


# ============================================================
# WORKER AISLADO
# ============================================================
# Modo interno invocado por el proceso principal para una sola huella.
# Devuelve JSON por la salida estándar; las excepciones se reportan como revisión.

if (

    len(sys.argv) >= 2

    and

    sys.argv[1] == "--worker"

):

    try:

        resultado = (

            procesar_un_archivo(

                sys.argv[2],

                sys.argv[3]

            )

        )


        print(

            json.dumps(

                resultado,

                ensure_ascii=False

            )

        )


        sys.exit(0)


    except Exception as error:

        resultado = {

            "estado":
                "REQUIERE_REVISION",

            "observaciones":
                str(error)
        }


        print(

            json.dumps(

                resultado,

                ensure_ascii=False

            )

        )


        sys.exit(2)


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================
# Valida el único argumento público: la carpeta raíz que contiene las personas.
# El modo --worker es interno y no debe usarse para ejecutar un lote manualmente.

if len(sys.argv) != 2:

    print()

    print(
        "Uso:"
    )

    print(

        'python3 '
        'corregir_huellas_dgire.py '
        '"/ruta/a/1010"'

    )

    print()

    sys.exit(1)


RAIZ = Path(

    sys.argv[1]

).expanduser().resolve()


if (

    not RAIZ.exists()

    or

    not RAIZ.is_dir()

):

    print()

    print(
        "ERROR: carpeta inválida:"
    )

    print(
        RAIZ
    )

    sys.exit(1)


# ============================================================
# COMPROBAR QUE EL CODEC RESPETA BITRATE
# ============================================================

def verificar_codec_variable():

    # Comprueba con un patrón sintético que dos bitrates producen tamaños distintos.
    # Detecta una instalación que todavía fuerza el bitrate fijo antes de iniciar
    # el lote. No sustituye la prueba de lectura de un WSQ real ni VeriFinger.

    y, x = np.indices(
        (
            512,
            512
        )
    )


    patron = (

        x * 17

        + y * 31

        + (
            (x // 8) % 2
        ) * 80

    ) % 256


    patron = patron.astype(
        np.uint8
    )


    img = Image.fromarray(
        patron
    ).convert("L")


    a = codificar_wsq(
        img,
        0.75
    )


    b = codificar_wsq(
        img,
        1.50
    )


    if len(a) == len(b):

        raise RuntimeError(

            "El codec sigue ignorando "
            "el bitrate. "

            "Revisa el parche "
            "de python-wsq."

        )


try:

    verificar_codec_variable()


except Exception as error:

    print()

    print(
        "ERROR DE CONFIGURACIÓN:"
    )

    print(
        error
    )

    print()

    sys.exit(1)


# ============================================================
# IDENTIFICAR PERSONAS
# ============================================================
# Cada subcarpeta inmediata visible se interpreta como una persona.
# No se verifica identidad; los nombres se usan únicamente para organizar rutas.

personas = sorted(

    [

        carpeta

        for carpeta
        in RAIZ.iterdir()

        if (

            carpeta.is_dir()

            and

            not carpeta.name.startswith(
                "."
            )

            and

            not carpeta.name.startswith(
                PREFIJO_CORREGIDAS
            )

        )

    ],

    key=lambda p:
    p.name.lower()
)


# ============================================================
# ENCONTRAR TODOS LOS WSQ ORIGINALES
# ============================================================
# Construye la lista de trabajos sin escribir aún los resultados.
# Conserva subrutas bajo cada persona y excluye carpetas de correcciones previas.
# Los WSQ situados directamente en la raíz no se incluyen.

trabajos = []


for persona in personas:

    for archivo in persona.rglob(
        "*"
    ):

        if not archivo.is_file():
            continue


        if (
            archivo.suffix.lower()
            != ".wsq"
        ):

            continue


        if es_carpeta_corregida(
            archivo
        ):

            continue


        relativa = (

            archivo.relative_to(
                persona
            )

        )


        destino = (

            persona

            / CARPETA_SALIDA

            / relativa

        )


        trabajos.append(

            (

                persona,

                archivo,

                destino,

                relativa

            )

        )


trabajos.sort(

    key=lambda x: (

        x[0].name.lower(),

        str(
            x[3]
        ).lower()

    )

)


# ============================================================
# PREVUELO
# ============================================================
# Presenta rutas, conteos y condiciones para que el operador revise el lote.
# Solo la respuesta SI inicia el procesamiento; cualquier otra lo cancela.

print()

print(
    "=" * 76
)

print(
    "       CORRECCIÓN DE HUELLAS DIGITALES DGIRE - V2"
)

print(
    "=" * 76
)

print()

print(
    f"Carpeta raíz:\n{RAIZ}"
)

print()

print(
    f"Carpetas de personas:    "
    f"{len(personas)}"
)

print(
    f"WSQ originales:          "
    f"{len(trabajos)}"
)

print()

print(
    "Los originales NO serán modificados."
)

print()

print(
    "Solo los archivos que superen "
    "TODAS las validaciones se escribirán."
)

print()

print(
    f"Salida: "
    f"{CARPETA_SALIDA}/"
)

print()

print(
    "Requisitos automáticos:"
)

print(
    "  512x512"
)

print(
    "  8 bits"
)

print(
    "  500 PPI"
)

print(
    "  15-40 KB"
)

print(
    "  relación efectiva cercana a 15:1"
)

print(
    "  crop sin resize"
)

print()


respuesta = input(

    "Escribe SI para iniciar: "

).strip().upper()


if respuesta != "SI":

    print(
        "Proceso cancelado."
    )

    sys.exit(0)


# ============================================================
# EJECUCIÓN
# ============================================================
# Procesa secuencialmente cada archivo con el mismo intérprete del entorno.
# Lee el JSON del trabajador o registra ERROR_PROCESO si no puede recuperarlo.
# Acumula filas en memoria: los CSV no se guardan hasta terminar el lote.

resultados = []


script_actual = Path(
    __file__
).resolve()


for numero, trabajo in enumerate(

    trabajos,

    start=1

):

    persona = trabajo[0]
    origen = trabajo[1]
    destino = trabajo[2]
    relativa = trabajo[3]


    print()

    print(

        f"[{numero}/"
        f"{len(trabajos)}]"

    )


    print(

        f"{persona.name} / "
        f"{relativa}"

    )


    destino.parent.mkdir(

        parents=True,

        exist_ok=True

    )


    proceso = subprocess.run(

        [

            sys.executable,

            str(
                script_actual
            ),

            "--worker",

            str(
                origen
            ),

            str(
                destino
            )

        ],

        capture_output=True,

        text=True
    )


    resultado = None


    try:

        lineas = [

            linea

            for linea
            in proceso.stdout.splitlines()

            if linea.strip()

        ]


        if lineas:

            resultado = json.loads(

                lineas[-1]

            )


    except Exception:

        resultado = None


    if resultado is None:

        resultado = {

            "estado":
                "ERROR_PROCESO",

            "observaciones":

                (

                    proceso.stderr.strip()

                    or

                    (
                        "Código de salida "
                        f"{proceso.returncode}"
                    )

                )

        }


    estado = resultado.get(

        "estado",

        "ERROR_PROCESO"

    )


    if (

        estado

        ==

        "OK_DGIRE_TECNICO"

    ):

        print(
            "  ✓ OK_DGIRE_TECNICO"
        )

        print(

            f"    "
            f"{resultado.get('kb_final')} KB"

            f" | "
            f"{resultado.get('ratio_efectivo')}:1"

            f" | bitrate "
            f"{resultado.get('bitrate_usado')}"

        )


        print(

            f"    crop: "

            f"x="
            f"{resultado.get('crop_left')}, "

            f"y="
            f"{resultado.get('crop_top')}"

        )


    else:

        print(

            f"  ⚠ {estado}"

        )


        print(

            f"    "
            f"{resultado.get('observaciones', '')}"

        )


    fila = {

        "persona":
            persona.name,

        "archivo_original":
            str(
                relativa
            ),

        "archivo_corregido":

            (

                str(
                    destino.relative_to(
                        persona
                    )
                )

                if destino.exists()

                else ""

            ),

        "estado":
            estado,

        "ancho_original":
            resultado.get(
                "ancho_original",
                ""
            ),

        "alto_original":
            resultado.get(
                "alto_original",
                ""
            ),

        "ancho_final":
            resultado.get(
                "ancho_final",
                ""
            ),

        "alto_final":
            resultado.get(
                "alto_final",
                ""
            ),

        "depth_final":
            resultado.get(
                "depth_final",
                ""
            ),

        "ppi_final":
            resultado.get(
                "ppi_final",
                ""
            ),

        "x_min":
            resultado.get(
                "x_min",
                ""
            ),

        "x_max":
            resultado.get(
                "x_max",
                ""
            ),

        "y_min":
            resultado.get(
                "y_min",
                ""
            ),

        "y_max":
            resultado.get(
                "y_max",
                ""
            ),

        "centro_x":
            resultado.get(
                "centro_x",
                ""
            ),

        "centro_y":
            resultado.get(
                "centro_y",
                ""
            ),

        "crop_left":
            resultado.get(
                "crop_left",
                ""
            ),

        "crop_top":
            resultado.get(
                "crop_top",
                ""
            ),

        "ancho_huella":
            resultado.get(
                "ancho_huella",
                ""
            ),

        "alto_huella":
            resultado.get(
                "alto_huella",
                ""
            ),

        "bbox_area_pct":
            resultado.get(
                "bbox_area_pct",
                ""
            ),

        "pixeles_fuera_pct":
            resultado.get(
                "pixeles_fuera_pct",
                ""
            ),

        "umbral":
            resultado.get(
                "umbral",
                ""
            ),

        "bitrate_usado":
            resultado.get(
                "bitrate_usado",
                ""
            ),

        "bitrate_nistcom":
            resultado.get(
                "bitrate_nistcom",
                ""
            ),

        "bytes_final":
            resultado.get(
                "bytes_final",
                ""
            ),

        "kb_final":
            resultado.get(
                "kb_final",
                ""
            ),

        "ratio_efectivo":
            resultado.get(
                "ratio_efectivo",
                ""
            ),

        "observaciones":
            resultado.get(
                "observaciones",
                ""
            )
    }


    resultados.append(
        fila
    )


# ============================================================
# REPORTE GENERAL
# ============================================================
# Exporta una fila por archivo encontrado, con resultado y mediciones disponibles.
# Sobrescribe el CSV anterior y usa UTF-8 con BOM para facilitar su importación.
# Los reportes incluyen rutas personales: no publicarlos con datos reales.

reporte = (

    RAIZ

    / "REPORTE_HUELLAS_DGIRE_V2.csv"

)


columnas = [

    "persona",

    "archivo_original",

    "archivo_corregido",

    "estado",

    "ancho_original",

    "alto_original",

    "ancho_final",

    "alto_final",

    "depth_final",

    "ppi_final",

    "x_min",

    "x_max",

    "y_min",

    "y_max",

    "centro_x",

    "centro_y",

    "crop_left",

    "crop_top",

    "ancho_huella",

    "alto_huella",

    "bbox_area_pct",

    "pixeles_fuera_pct",

    "umbral",

    "bitrate_usado",

    "bitrate_nistcom",

    "bytes_final",

    "kb_final",

    "ratio_efectivo",

    "observaciones"
]


with open(

    reporte,

    "w",

    newline="",

    encoding="utf-8-sig"

) as archivo_csv:


    escritor = csv.DictWriter(

        archivo_csv,

        fieldnames=columnas

    )


    escritor.writeheader()


    escritor.writerows(

        resultados

    )


# ============================================================
# RESUMEN POR PERSONA
# ============================================================
# Agrupa resultados técnicos; todo estado distinto de OK cuenta como revisión.
# Tener dos archivos OK no demuestra que sean dedos distintos ni ambas manos.
# Las carpetas sin archivos procesados no aparecen como filas en este resumen.

conteo_persona = defaultdict(

    lambda: {

        "total": 0,

        "ok": 0,

        "revision": 0

    }

)


for fila in resultados:

    p = fila["persona"]


    conteo_persona[
        p
    ]["total"] += 1


    if (

        fila["estado"]

        ==

        "OK_DGIRE_TECNICO"

    ):

        conteo_persona[
            p
        ]["ok"] += 1


    else:

        conteo_persona[
            p
        ]["revision"] += 1


reporte_personas = (

    RAIZ

    / "RESUMEN_PERSONAS_DGIRE_V2.csv"

)


with open(

    reporte_personas,

    "w",

    newline="",

    encoding="utf-8-sig"

) as archivo_csv:


    campos = [

        "persona",

        "wsq_originales",

        "wsq_ok_tecnico",

        "wsq_revision",

        "tiene_al_menos_2_ok"

    ]


    escritor = csv.DictWriter(

        archivo_csv,

        fieldnames=campos

    )


    escritor.writeheader()


    for persona_nombre in sorted(

        conteo_persona.keys(),

        key=str.lower

    ):


        c = conteo_persona[
            persona_nombre
        ]


        escritor.writerow({

            "persona":
                persona_nombre,

            "wsq_originales":
                c["total"],

            "wsq_ok_tecnico":
                c["ok"],

            "wsq_revision":
                c["revision"],

            "tiene_al_menos_2_ok":

                (
                    "SI"

                    if c["ok"] >= 2

                    else "NO"
                )

        })


# ============================================================
# RESUMEN FINAL
# ============================================================
# Muestra los conteos y las ubicaciones de los reportes de esta ejecución.
# Completar después la revisión visual y la validación biométrica con VeriFinger.

correctos = sum(

    1

    for r in resultados

    if (

        r["estado"]

        ==

        "OK_DGIRE_TECNICO"

    )

)


revision = (

    len(resultados)

    - correctos

)


personas_con_2 = sum(

    1

    for c
    in conteo_persona.values()

    if c["ok"] >= 2

)


print()

print()

print(
    "=" * 76
)

print(
    "                  PROCESO FINALIZADO"
)

print(
    "=" * 76
)

print(

    f"WSQ procesados:          "
    f"{len(resultados)}"

)

print(

    f"OK técnico DGIRE:        "
    f"{correctos}"

)

print(

    f"Requieren revisión:      "
    f"{revision}"

)

print(

    f"Personas con >=2 OK:     "
    f"{personas_con_2}/"
    f"{len(personas)}"

)

print()

print(
    "Reporte general:"
)

print(
    reporte
)

print()

print(
    "Resumen por persona:"
)

print(
    reporte_personas
)

print(
    "=" * 76
)

print()
