# Procesamiento masivo de huellas WSQ para DGIRE

Documentación de la versión **V2** de `corregir_huellas_dgire.py`, desarrollada para localizar la región de una huella, recortarla a 512 × 512 píxeles y generar un nuevo WSQ con controles técnicos y reportes CSV.

El flujo se diseñó para capturas de 800 × 750 píxeles con fondo claro y crestas oscuras. El programa admite imágenes con ambas dimensiones de al menos 512 píxeles, siempre que el recorte supere sus controles. **No escala, estira ni amplía las huellas.**

Este README debe acompañar al script V2 en el repositorio; no contiene el programa completo. Todos los identificadores de personas empleados en los ejemplos son ficticios.

## Precauciones antes de empezar

- Conservar un respaldo íntegro de los originales fuera de la carpeta que se procesará. Trabajar sobre una copia del lote.
- No modificar ni reemplazar los WSQ originales. El script guarda sus resultados en `HUELLAS_DIGITALES_CORREGIDAS_V2` dentro de cada carpeta de persona.
- Respaldar también las salidas y los CSV antes de repetir una ejecución: **V2 elimina cada destino existente antes de reprocesarlo**, y sobrescribe los reportes al finalizar. Si ese archivo falla, su resultado anterior puede desaparecer.
- No usar `resize`, interpolación ni ampliación para forzar el encuadre o la cobertura. Si la captura no sirve, revisar el caso o repetir la toma.
- WSQ usa compresión con pérdida: recortar conserva la escala geométrica, pero volver a codificar puede modificar intensidades. Procesar siempre desde el original y evitar cadenas de recompresión o pasos intermedios por JPEG.
- **La validación biométrica final debe hacerse con VeriFinger.** Un `OK_DGIRE_TECNICO` no acredita por sí solo calidad biométrica, identidad, enrolamiento ni aceptación por DGIRE.

## Requisitos DGIRE y alcance de los controles

El instructivo de DGIRE establece los siguientes parámetros para huellas. Consultar la documentación aplicable al trámite antes de una nueva entrega; este proyecto documenta el flujo desarrollado, no certifica vigencia normativa. Fuente: [instructivo de características técnicas de biométricos, DGIRE](https://dgire.unam.mx/media/attachments/2025/03/14/caracterisiticas_bio_planteles_200818.pdf).

| Aspecto | Requisito del instructivo | Control de V2 |
|---|---|---|
| Formato | Un WSQ por dedo | Codifica y decodifica WSQ |
| Dimensiones | 512 × 512 píxeles | Verifica ambas dimensiones |
| Profundidad | 8 bits, 256 grises | Convierte a modo `L`; comprueba raster de 262 144 bytes |
| Resolución | 500 dpi | Verifica 500 PPI en la salida decodificada |
| Compresión | 15:1 | Busca una relación efectiva próxima a 15:1 |
| Tamaño | 15–40 KB, interpretados así por este flujo | Exige 15 360–40 000 bytes |
| Encuadre | Huella centrada y cobertura mínima del 60 % | Centrado aproximado; cobertura solo orientativa |
| Cantidad | Dos huellas, normalmente ambos pulgares | Cuenta archivos; no identifica dedos |

Las tolerancias de **13.5:1–16.5:1** y **1.5 % de región detectada fuera del recorte** son decisiones del algoritmo, no tolerancias oficiales de DGIRE. El campo `bbox_area_pct` tampoco demuestra el cumplimiento del 60 %: mide un rectángulo aproximado, no calidad biométrica ni una interpretación oficial de cobertura.

Escribir 500 PPI en el archivo no corrige una captura realizada a otra resolución física. Confirmar previamente que el dispositivo capturó a 500 dpi; V2 comprueba el PPI de salida, no verifica el del original.

## Lógica del algoritmo

```text
Inventariar WSQ originales por persona
  → abrir WSQ y convertir a escala de grises de 8 bits
  → localizar aproximadamente la región de huella
  → elegir una ventana de 512 × 512 que preserve la región detectada
  → recortar sin cambiar la escala
  → buscar bitrate WSQ que cumpla tamaño y relación efectiva
  → validar en memoria, escribir y validar desde disco
  → generar reportes técnicos
  → inspeccionar y validar con VeriFinger
```

1. **Descubrimiento.** Cada subcarpeta inmediata no oculta de la raíz representa una persona. Busca `.wsq` sin distinguir mayúsculas dentro de ella y sus subcarpetas. Excluye rutas que contengan componentes cuyo nombre comience con `HUELLAS_DIGITALES_CORREGIDAS`, incluidas V1 y V2. Los WSQ directamente en la raíz no se procesan.
2. **Detección.** Estima el fondo mediante la mediana de los bordes. Combina ese valor con el umbral de Otsu: `clip(min(fondo - 8, otsu + 20), 70, 245)`. La máscara contiene píxeles más oscuros que el umbral. Filtra filas y columnas con pocos píxeles oscuros; si elimina demasiado, vuelve a la máscara inicial. Exige al menos 500 píxeles detectados.
3. **Centro robusto.** Calcula límites mediante los percentiles 1 y 99 de las coordenadas de la máscara para reducir la influencia de manchas aisladas. No busca minutias ni un centro biométrico.
4. **Ventana.** Usa sumas acumuladas —imagen integral— para evaluar ventanas de 512 × 512. Entre las que conservan casi el máximo de máscara, escoge la más cercana al centro robusto. Tolera una diferencia de aproximadamente 0.15 % respecto al máximo al elegir candidatas. Rechaza el archivo si deja fuera más de 1.5 % de la máscara. Esta heurística no garantiza conservar todas las crestas reales.
5. **Recorte.** Extrae la ventana sin `resize` ni padding. Si alguna dimensión original es menor que 512, requiere revisión. Incluso una imagen de 512 × 512 pasa por el flujo de detección y codificación; no se copia directamente.
6. **Compresión.** Prueba primero bitrate `0.75`. Si no cumple, prueba los extremos `0.35` y `2.25` y realiza 11 iteraciones de búsqueda. Elige entre candidatos válidos el más cercano a `round(262144 / 15) = 17476` bytes. La relación efectiva es `262144 / bytes_del_WSQ`, incluido el contenedor. El bitrate no es una relación de compresión exacta.
7. **Verificación.** Decodifica los bytes y comprueba dimensiones, PPI y longitud del raster; exige tamaño y relación dentro de los intervalos configurados. Escribe y vuelve a validar desde disco.
8. **Aislamiento.** Ejecuta cada archivo secuencialmente en un subproceso `--worker`. Puede registrar un fallo nativo del proceso y continuar con otros archivos. No ofrece recuperación general frente a interrupciones, fallos del proceso principal o del almacenamiento.

La V2 reemplaza el rectángulo rígido de la primera revisión por esta búsqueda de ventana y añade la selección de bitrate. No modifica los píxeles mediante la máscara: la máscara solo decide dónde recortar.

## Preparar macOS

Se necesita Python, herramientas de compilación C, Git y las bibliotecas Pillow, NumPy y `wsq`. El problema de compatibilidad observado apareció con Python 3.14 en Apple Silicon ARM64.

Instalar las herramientas de Apple y esperar a que termine el instalador:

```bash
xcode-select --install
```

Si ya están instaladas, continuar. Instalar Homebrew siguiendo su [sitio oficial](https://brew.sh/) si no está disponible. Para reproducir la rama de Python usada en este flujo:

```bash
brew install python@3.14
python3.14 -m venv "$HOME/wsq-env"
source "$HOME/wsq-env/bin/activate"
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install pillow numpy
python3 -c 'import sys, platform; print(sys.version); print(platform.machine()); print(sys.executable)'
```

En Apple Silicon con ejecución nativa, la arquitectura debe ser `arm64`. Si `python3.14` no está en el PATH, usar `"$(brew --prefix python@3.14)/bin/python3.14"` para crear el entorno. Evitar mezclar un Python x86_64 bajo Rosetta con bibliotecas ARM64.

No basta con instalar `wsq` desde PyPI para reproducir este flujo: se necesita la versión local parcheada descrita a continuación.

## Parche de python-wsq

El [código de python-wsq](https://github.com/idemia/python-wsq) revisado contiene dos comportamientos relevantes: `decompress` declara como `int` una longitud que Python entrega como `Py_ssize_t`, y `compress` sobrescribe el bitrate recibido con `0.75`. El primero puede causar corrupción de memoria en 64 bits; el segundo impide ajustar el tamaño final. Al liberar el bitrate también se cambia el valor predeterminado de escritura de Pillow a `0.75`.

### Obtener y respaldar el código

Con el entorno activo:

```bash
cd "$HOME/Downloads"
git clone https://github.com/idemia/python-wsq.git python-wsq-fixed
cd python-wsq-fixed
cp -n csrc/_wsq.c csrc/_wsq.c.backup
cp -n wsq/WsqImagePlugin.py wsq/WsqImagePlugin.py.backup
git rev-parse HEAD
```

Guardar el identificador del commit para reproducibilidad. Si `python-wsq-fixed` ya existe, entrar en ella e inspeccionar `git diff`; no clonar encima ni descartar cambios previos. Las copias con `cp -n` no reemplazan respaldos existentes.

### Aplicar los cambios

Ejecutar el bloque completo desde `python-wsq-fixed`. Comprueba los fragmentos antes de escribir y admite una copia que ya tenga estos cambios. Si el código del proyecto cambió, se detiene para revisión en lugar de afirmar que aplicó un parche inexistente.

```bash
python3 - <<'PY'
from pathlib import Path

c_path = Path('csrc/_wsq.c')
p_path = Path('wsq/WsqImagePlugin.py')
c = c_path.read_text()
p = p_path.read_text()

def cambiar(texto, anterior, nuevo):
    if anterior in texto:
        if texto.count(anterior) != 1:
            raise SystemExit('Fragmento ambiguo: revisar el código; no se escribió nada.')
        return texto.replace(anterior, nuevo, 1)
    if nuevo in texto:
        return texto
    raise SystemExit('Código diferente al esperado; no se escribió nada. Revisar versión.')

c = cambiar(c,
    '    unsigned char* buffer;\n    int buffer_size;\n    // output data',
    '    unsigned char* buffer;\n    Py_ssize_t buffer_size;\n    // output data')
c = cambiar(c,
    '&out_lossy_flag, buffer,buffer_size);',
    '&out_lossy_flag, buffer,(int)buffer_size);')
c = cambiar(c,
    '    ratio = 0.75;   // 15:1 fixed ratio (2.25==>5:1, .75==>15:1)',
    '    /* Use bitrate supplied by caller. */')
p = cambiar(p, '(12,))])', '(0.75,))])')

c_path.write_text(c)
p_path.write_text(p)
print('Parche aplicado o ya presente.')
PY
```

La conversión a `int` conserva la interfaz del decodificador NBIS para archivos de este tamaño. Este parche puntual no constituye una auditoría general del códec.

### Compilar e instalar

```bash
python3 -m pip install --force-reinstall --no-cache-dir --no-deps .
python3 -c "import wsq, _wsq; print('WSQ listo'); print(_wsq.__file__)"
```

No actualizar posteriormente `wsq` desde PyPI sin revisar si se perderían los parches. Si se cambia de versión de Python o arquitectura, reconstruir el entorno y compilar de nuevo.

### Probar el códec antes del lote

Este patrón es sintético y no contiene una huella real:

```bash
python3 - <<'PY'
import numpy as np
import _wsq

y, x = np.indices((512, 512))
patron = ((x * 17 + y * 31 + ((x // 8) % 2) * 80) % 256).astype('uint8')
tamanos = []
for bitrate in (0.75, 1.00, 1.50):
    data = _wsq.compress(patron.tobytes(), 512, 512, bitrate)
    raw, ancho, alto, ppi = _wsq.decompress(data)
    assert (ancho, alto, ppi, len(raw)) == (512, 512, 500, 262144)
    tamanos.append(len(data))
    print(f'Bitrate {bitrate}: {len(data) / 1024:.2f} KiB')
assert len(set(tamanos)) == 3, 'Revisar: el códec podría ignorar el bitrate.'
print('Codificación variable y decodificación correctas.')
PY
```

Los tamaños concretos pueden variar. Probar además la lectura de un original local, sustituyendo el identificador ficticio por una ruta existente:

```bash
python3 -c 'from PIL import Image; import wsq, sys; im=Image.open(sys.argv[1]); im.load(); print(im.size, im.mode)' "$HOME/Downloads/1010/PERSONA_FICTICIA_001/DER.wsq"
```

Para el tipo de captura que originó este flujo se espera `(800, 750) L`. Importar el módulo sin error no demuestra que pueda decodificar un archivo: realizar ambas pruebas.

## Estructura de archivos

Guardar el script V2 junto a este README. Mantener los datos fuera del repositorio:

```text
proyecto-wsq/
├── README.md
└── corregir_huellas_dgire.py

1010/
├── PERSONA_FICTICIA_001/
│   ├── DER.wsq
│   └── IZQ.wsq
└── PERSONA_FICTICIA_002/
    └── CAPTURAS/
        ├── DER.wsq
        └── IZQ.wsq
```

`1010` es el nombre usado como ejemplo, no un valor obligatorio. Pasar la raíz del lote, no la carpeta de una persona. No guardar respaldos dentro de esa raíz: podrían contarse como personas o procesarse como nuevos originales. Evitar enlaces simbólicos y alias entre entradas y salidas.

La salida conserva nombres y subrutas:

```text
1010/
├── PERSONA_FICTICIA_001/
│   ├── DER.wsq
│   ├── IZQ.wsq
│   └── HUELLAS_DIGITALES_CORREGIDAS_V2/
│       ├── DER.wsq
│       └── IZQ.wsq
├── PERSONA_FICTICIA_002/
│   ├── CAPTURAS/
│   │   ├── DER.wsq
│   │   └── IZQ.wsq
│   └── HUELLAS_DIGITALES_CORREGIDAS_V2/
│       └── CAPTURAS/
│           ├── DER.wsq
│           └── IZQ.wsq
├── REPORTE_HUELLAS_DGIRE_V2.csv
└── RESUMEN_PERSONAS_DGIRE_V2.csv
```

## Ejecutar el programa

1. Respaldar el lote y cualquier resultado anterior. Probar primero con una copia pequeña que mantenga la estructura raíz/persona/archivos.
2. Activar el entorno y entrar en el directorio donde se guardó el script.
3. Ejecutar:

```bash
source "$HOME/wsq-env/bin/activate"
python3 corregir_huellas_dgire.py "$HOME/Downloads/1010"
```

Si el script está en el Escritorio, la alternativa es:

```bash
python3 "$HOME/Desktop/corregir_huellas_dgire.py" "$HOME/Downloads/1010"
```

4. Revisar la raíz y los conteos del resumen inicial. Escribir `SI` para iniciar; otra respuesta cancela. El programa verifica el bitrate antes de pedir esta confirmación.
5. Esperar el resumen final y revisar **ambos CSV**. No asumir éxito solo porque el programa terminó.

Los CSV se escriben al final, no después de cada archivo. Una interrupción puede dejar salidas parciales y reportes antiguos. Una nueva ejecución procesa otra vez los originales encontrados; no es una reanudación selectiva. Tampoco elimina automáticamente salidas huérfanas de originales que ya no existan. Para un nuevo lote reproducible, partir de una copia limpia de los originales.

## Reportes CSV y estados

Ambos reportes usan separador coma y `utf-8-sig` para facilitar su apertura en aplicaciones de hojas de cálculo. Si todo aparece en una sola columna, importar indicando coma como delimitador.

### REPORTE_HUELLAS_DGIRE_V2.csv

Contiene una fila por WSQ encontrado en la ejecución:

| Estado | Significado y acción |
|---|---|
| `OK_DGIRE_TECNICO` | Superó los controles implementados. Pendiente de revisión visual y VeriFinger. |
| `REQUIERE_REVISION` | El trabajador capturó una excepción: detección, dimensiones, recorte, compresión, validación o escritura. Consultar `observaciones`. |
| `ERROR_PROCESO` | No hubo una respuesta JSON interpretable del trabajador; puede ser un cierre nativo. Consultar error o código de salida en `observaciones`. |

En filas fallidas, los campos de medición pueden estar vacíos. Un fallo tras la escritura puede dejar un archivo en disco: **la mera presencia de una salida no la valida**.

| Campos | Interpretación |
|---|---|
| `persona`, `archivo_original`, `archivo_corregido` | Identificación de la carpeta y rutas de entrada/salida |
| `estado`, `observaciones` | Resultado técnico y explicación |
| `ancho_original`, `alto_original` | Dimensiones de entrada en píxeles |
| `ancho_final`, `alto_final`, `depth_final`, `ppi_final` | Dimensiones y características de salida; profundidad declarada por el flujo, coherente con el raster de 8 bits |
| `x_min`, `x_max`, `y_min`, `y_max` | Límites robustos de la región en coordenadas de la imagen original |
| `centro_x`, `centro_y` | Centro del rectángulo robusto |
| `crop_left`, `crop_top` | Esquina superior izquierda del recorte; derecha y abajo se obtienen sumando 512 |
| `ancho_huella`, `alto_huella` | Dimensiones del rectángulo robusto |
| `bbox_area_pct` | Área de ese rectángulo dividida entre 512 × 512, en porcentaje; orientativa |
| `pixeles_fuera_pct` | Porcentaje de la máscara detectada fuera de la ventana |
| `umbral` | Intensidad usada para construir la máscara |
| `bitrate_usado` | Parámetro suministrado al codificador |
| `bitrate_nistcom` | Valor leído de `WSQ_BITRATE`, si está disponible; vacío no equivale a cero |
| `bytes_final`, `kb_final` | Tamaño del archivo; aunque se llama `kb_final`, representa KiB: bytes / 1024 |
| `ratio_efectivo` | 262 144 bytes del raster / tamaño total del WSQ |

Las coordenadas parten de cero, con origen en la esquina superior izquierda. `fondo_estimado` se calcula internamente, pero no se exporta como columna del CSV V2.

### RESUMEN_PERSONAS_DGIRE_V2.csv

| Campo | Significado |
|---|---|
| `persona` | Carpeta de la persona |
| `wsq_originales` | Archivos encontrados para esa persona |
| `wsq_ok_tecnico` | Cantidad con `OK_DGIRE_TECNICO` |
| `wsq_revision` | Cantidad con cualquier otro estado, incluidos errores de proceso |
| `tiene_al_menos_2_ok` | `SI` cuando hay dos o más resultados técnicos correctos |

Este resumen no detecta duplicados ni comprueba que los archivos correspondan a manos distintas. Las carpetas sin WSQ no generan una fila; compararlas también con el inventario del lote. Los reportes V1 sin sufijo `_V2` son históricos y no describen esta ejecución.

## Validación final y entrega

1. Resolver todas las filas de revisión y error; cotejar cantidades con el inventario, incluidas personas sin archivos.
2. Comparar visualmente originales y resultados: centrado, crestas completas, contraste y ausencia de bordes añadidos. Revisar especialmente los casos con región fuera del recorte o cobertura dudosa.
3. Confirmar la correspondencia de persona y dedo; dos archivos correctos no garantizan dos dedos distintos.
4. **Validar los WSQ finales con VeriFinger**, comprobando calidad y posibilidad de enrolamiento. Este programa no integra ni ejecuta VeriFinger y no calcula una puntuación biométrica equivalente.
5. Si la captura no permite el encuadre, cobertura o calidad requeridos, repetirla; no agrandar ni deformar la huella para superar una comprobación.
6. Conservar originales, salidas aprobadas, reportes y versiones del entorno hasta completar la aceptación. Entregar únicamente resultados revisados conforme al procedimiento institucional.

## Limpieza de la primera revisión

Realizarla **solo después de validar V2 y disponer de respaldo**. Estos comandos son opcionales y borran carpetas antiguas; no forman parte del procesamiento automático.

Entrar en la raíz y revisar la ubicación:

```bash
cd "$HOME/Downloads/1010"
pwd
find . -type d -name 'HUELLAS_DIGITALES_CORREGIDAS' -prune -print
find . -type d -name 'HUELLAS_DIGITALES_CORREGIDAS' -prune -print | wc -l
```

Inspeccionar la lista y confirmar que esas carpetas contienen solo resultados V1 respaldados. **El siguiente comando elimina su contenido de forma permanente, sin enviarlo a la Papelera:**

```bash
find . -type d -name 'HUELLAS_DIGITALES_CORREGIDAS' -prune -exec rm -rf {} +
```

El nombre debe coincidir exactamente. No añadir comodines: `HUELLAS_DIGITALES_CORREGIDAS_V2` debe conservarse. Antes de borrar, comprobar también que no se hayan guardado resultados V2 dentro de una carpeta V1.

Verificar después:

```bash
find . -type d -name 'HUELLAS_DIGITALES_CORREGIDAS' -prune -print
find . -type d -name 'HUELLAS_DIGITALES_CORREGIDAS_V2' -prune -print
```

La primera consulta debería quedar vacía. Conservar el nombre V2 mantiene coherencia con el script y los reportes; renombrarlo no es necesario.

## Solución de problemas

| Síntoma | Qué revisar |
|---|---|
| `ModuleNotFoundError` para `PIL`, `numpy`, `wsq` o `_wsq` | Activar `wsq-env`; usar `python3 -m pip` del mismo entorno e instalar las dependencias/parche. |
| Falla de compilación o compilador ausente | Completar Xcode Command Line Tools; comprobar `xcode-select -p` y que Python y las bibliotecas usan la misma arquitectura. |
| `SIGBUS`, `EXC_BAD_ACCESS` o cierre al abrir WSQ | Confirmar el cambio de `buffer_size` y recompilar. Probar un único archivo y comprobar `_wsq.__file__`. Un archivo dañado también puede fallar. |
| «El codec sigue ignorando el bitrate» | Verificar que se quitó la asignación fija `ratio = 0.75`, reinstalar la copia local y repetir la prueba sintética. |
| «Código diferente al esperado» al parchear | Revisar commit y `git diff`. No continuar con reemplazos a ciegas; el proyecto puede haber cambiado o incorporado una corrección distinta. |
| `Unknown marker`, falta de SOF o error de decodificación | Verificar que sea realmente WSQ y que no esté truncado; recuperar desde respaldo o recapturar. Renombrar una extensión no convierte un formato. |
| Imagen menor que 512 × 512 | V2 no añade padding ni escala. Revisar la captura y el flujo adecuado antes de procesar. |
| No se detecta suficiente región de huella | Revisar fondo, contraste, imagen vacía o formato inesperado. No bajar umbrales solo para obtener un estado correcto. |
| El recorte dejaría demasiada huella fuera | Comparar visualmente la máscara/encuadre con el original y considerar una nueva toma. |
| No se encuentra codificación válida | Verificar primero el parche; después revisar la imagen y las restricciones. No inflar archivos con bytes de relleno ni forzar parámetros para simular cumplimiento. |
| Cero archivos o conteos inesperados | Pasar la raíz del lote, revisar subcarpetas y exclusiones por prefijo. El script no procesa WSQ directamente en la raíz. |
| Permiso denegado o disco lleno | Revisar permisos de lectura/escritura y espacio. Verificar las salidas parciales antes de repetir. |
| CSV antiguo tras interrupción | Los reportes se regeneran al terminar. Respaldar resultados y repetir desde originales; no usar un CSV de otra ejecución como evidencia actual. |
| Hay dos `OK`, pero falta una mano | El programa cuenta archivos, no identifica anatomía ni duplicados. Revisar correspondencia manualmente. |

## Publicar en GitHub y reproducir el entorno

Publicar el código, esta documentación y, si se desea, pruebas con patrones sintéticos. **No subir WSQ reales, vistas previas biométricas, reportes del lote, respaldos ni rutas o nombres personales.** Cambiar el nombre de una persona no anonimiza una huella.

Ejemplo de reglas para `.gitignore`:

```gitignore
# Datos y resultados locales
1010/
*.[wW][sS][qQ]
HUELLAS_DIGITALES_CORREGIDAS*/
REPORTE_HUELLAS_DGIRE*.csv
RESUMEN_PERSONAS_DGIRE*.csv

# Entornos y archivos temporales
.venv/
wsq-env/
__pycache__/
*.pyc
*.backup
.DS_Store
```

Agregar reglas explícitas para otros lotes, imágenes de inspección y respaldos. `.gitignore` no retira archivos ya rastreados: revisar el contenido que se publicará y el historial antes de subirlo.

Registrar la versión de Python, arquitectura, versiones de Pillow/NumPy/wsq y commit de `python-wsq`. `python3 -m pip freeze` ayuda a inventariar dependencias, pero revisar su salida antes de publicarla: una instalación local puede incluir rutas personales. Un `requirements.txt` que solo declare `wsq` no reproduce el parche; conservar también sus instrucciones o un diff revisado sin datos privados.

## Referencias

- [DGIRE: características técnicas para la toma de biométricos](https://dgire.unam.mx/media/attachments/2025/03/14/caracterisiticas_bio_planteles_200818.pdf).
- [Documento DGIRE 2019 usado como referencia en el desarrollo](https://www.dgire.unam.mx/webdgire/wp-content/uploads/2020/10/2019_Caracterisiticas_tecnicas_biometricos.pdf). Si su enlace histórico no está disponible, solicitar el instructivo aplicable a DGIRE.
- [IDEMIA: python-wsq](https://github.com/idemia/python-wsq), incluido el código de [la extensión C](https://github.com/idemia/python-wsq/blob/master/csrc/_wsq.c) y [el complemento de Pillow](https://github.com/idemia/python-wsq/blob/master/wsq/WsqImagePlugin.py).

La documentación describe la implementación V2 revisada. Sus controles técnicos y tolerancias internas no equivalen a una certificación del codificador ni sustituyen la validación biométrica con VeriFinger.
